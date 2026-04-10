SERVER     := kolberg
REMOTE_DIR := ~/n8n
TEST_PATH  ?= apps
DEPLOY_AT  ?=
BRANCH     := $(shell git rev-parse --abbrev-ref HEAD)

.DEFAULT_GOAL := help
.PHONY: help push test deploy makemigrations rollback

help:
	@echo ""
	@echo "  make push            — проверить коммиты и отправить ветку в GitHub"
	@echo "  make test            — запустить тесты на сервере"
	@echo "  make deploy          — задеплоить main в production"
	@echo "  make deploy DEPLOY_AT=23:00 — задеплоить в указанное время"
	@echo "  make makemigrations  — создать миграции и скачать на локал"
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
	ssh $(SERVER) "bash $(REMOTE_DIR)/deploy.sh $(DEPLOY_AT)"

# ── 4. Миграции ───────────────────────────────────────────────────────────────
makemigrations:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py makemigrations"
	rsync -av --omit-dir-times \
		$(SERVER):$(REMOTE_DIR)/backend_v2/migrations/ \
		./backend_v2/migrations/

# ── 5. Откат ──────────────────────────────────────────────────────────────────
rollback:
	@echo "⚠️  Откат production на предыдущий образ..."
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker tag n8n-backend_v2:previous n8n-backend_v2:latest 2>/dev/null && \
		docker tag n8n-frontend_v2:previous n8n-frontend_v2:latest 2>/dev/null && \
		docker compose --env-file ./.env up -d --no-deps backend_v2 frontend_v2"
	@echo "✅  Откат выполнен."
