SERVER     := kolberg
REMOTE_DIR := ~/n8n
TEST_PATH  ?= apps
DEPLOY_AT  ?=
DEPLOY_RUN_TESTS ?= 1
DEPLOY_TEST_PATH ?= $(TEST_PATH)
BRANCH     := $(shell git rev-parse --abbrev-ref HEAD)

.DEFAULT_GOAL := help
.PHONY: help push test deploy makemigrations showmigrations rollback refresh-approval-messages

help:
	@echo ""
	@echo "  make push            — проверить коммиты и отправить ветку в GitHub"
	@echo "  make test            — запустить тесты на сервере"
	@echo "  make deploy          — задеплоить main в production"
	@echo "  make deploy DEPLOY_AT=23:00 — задеплоить в указанное время"
	@echo "  make deploy DEPLOY_RUN_TESTS=0 — деплой без пост-тестов"
	@echo "  make deploy DEPLOY_TEST_PATH=apps.modules.requests.tests — деплой + таргетные тесты"
	@echo "  make makemigrations  — создать миграции и скачать на локал"
	@echo "  make showmigrations  — показать tenants/requests/vendors миграции на сервере"
	@echo "  make refresh-approval-messages REQUEST_IDS='1 2' — актуализировать Telegram-карточки заявок на сервере"
	@echo "  make rollback        — откатить production на предыдущий образ"
	@echo ""

# ── 1. Отправить ветку в GitHub ───────────────────────────────────────────────
push:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "❌  Есть незакоммиченные изменения. Сначала git commit."; \
		git status --short; \
		exit 1; \
	fi
	@if [ "$(BRANCH)" = "main" ]; then \
		echo "❌  Нельзя пушить напрямую в main. Используй dev-ветку."; \
		exit 1; \
	fi
	git push origin $(BRANCH)
	@echo "✅  Ветка $(BRANCH) отправлена в GitHub."
	@echo "    Теперь создай PR: main ← $(BRANCH)"

# ── 2. Тесты на сервере ───────────────────────────────────────────────────────
test:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		git pull --ff-only && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py test $(TEST_PATH) --keepdb -v 2"

# ── 3. Деплой в production (только из main) ───────────────────────────────────
deploy:
	@if [ "$(BRANCH)" != "main" ]; then \
		echo "❌  Деплой только из ветки main. Сейчас: $(BRANCH)"; \
		echo "    Смержи PR и переключись: git checkout main && git pull"; \
		exit 1; \
	fi
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "❌  Есть незакоммиченные изменения."; \
		exit 1; \
	fi
	ssh $(SERVER) "DEPLOY_RUN_TESTS=$(DEPLOY_RUN_TESTS) DEPLOY_TEST_PATH='$(DEPLOY_TEST_PATH)' bash $(REMOTE_DIR)/deploy.sh $(DEPLOY_AT)"

# ── 4. Миграции ───────────────────────────────────────────────────────────────
makemigrations:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py makemigrations"
	rsync -av --omit-dir-times \
		--include='*/' \
		--include='migrations/***' \
		--exclude='*' \
		$(SERVER):$(REMOTE_DIR)/backend_v2/apps/ \
		./backend_v2/apps/

# ── 5. Миграции: статус ───────────────────────────────────────────────────────
showmigrations:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py showmigrations tenants requests vendors"

# ── 6. Telegram: актуализация карточек согласований по ID заявок (на сервере) ─
REQUEST_IDS ?=

refresh-approval-messages:
	@if [ -z "$(REQUEST_IDS)" ]; then \
		echo "Usage: make refresh-approval-messages REQUEST_IDS='123'"; \
		echo "  или: make refresh-approval-messages REQUEST_IDS='1 2 3'"; \
		exit 1; \
	fi
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py refresh_telegram_approval_messages $(REQUEST_IDS)"

# ── 7. Откат production ──────────────────────────────────────────────────────
rollback:
	@echo "⚠️  Откат production на предыдущий образ..."
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker tag n8n-backend_v2:previous n8n-backend_v2:latest 2>/dev/null && \
		docker tag n8n-frontend_v2:previous n8n-frontend_v2:latest 2>/dev/null && \
		docker compose --env-file ./.env up -d --no-deps backend_v2 frontend_v2"
	@echo "✅  Откат выполнен."
