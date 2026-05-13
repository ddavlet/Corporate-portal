SERVER     := kolberg
REMOTE_DIR := ~/n8n
TEST_PATH  ?= apps
DEPLOY_AT  ?=
DEPLOY_RUN_TESTS ?= 1
DEPLOY_TEST_PATH ?= $(TEST_PATH)
BRANCH     := $(shell git rev-parse --abbrev-ref HEAD)

.DEFAULT_GOAL := help
.PHONY: help push test deploy deploy-fast makemigrations showmigrations backup-db rollback refresh-approval-messages local-up local-down local-logs

help:
	@echo ""
	@echo "  make push            — проверить коммиты и отправить ветку в GitHub"
	@echo "  make test            — запустить тесты на сервере"
	@echo "  make deploy          — задеплоить main (после перезапуска: пост-тесты $(DEPLOY_TEST_PATH), обычно несколько минут)"
	@echo "  make deploy-fast     — то же без пост-тестов (быстрее; полный прогон — в GitHub Actions на PR)"
	@echo "  make deploy DEPLOY_AT=23:00 — задеплоить в указанное время"
	@echo "  make deploy DEPLOY_RUN_TESTS=0 — как deploy-fast: без пост-тестов"
	@echo "  make deploy DEPLOY_TEST_PATH=apps.modules.requests.tests — пост-тесты только по модулю"
	@echo "  make makemigrations  — создать миграции и скачать на локал"
	@echo "  make showmigrations  — показать tenants/requests/vendors миграции на сервере"
	@echo "  make backup-db       — создать gzip-копию БД на сервере в backups/db"
	@echo "  make refresh-approval-messages REQUEST_IDS='1 2' — актуализировать Telegram-карточки заявок на сервере"
	@echo "  make local-up        — поднять docker-compose.local.yml локально"
	@echo "  make local-down      — остановить локальный compose (без удаления volumes)"
	@echo "  make local-logs      — логи локального compose"
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

# Быстрый деплой: без повторного прогона всего apps на сервере (полный прогон — в GitHub Actions на PR).
deploy-fast:
	@$(MAKE) deploy DEPLOY_RUN_TESTS=0

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

# ── 6. Ручной backup БД на сервере (перед миграциями) ─────────────────────────
BACKUP_NAME ?= manual_$(shell date +%Y%m%d_%H%M%S)

# Переменные POSTGRES_* должны раскрываться во внутреннем sh контейнера db, не в ssh-сессии
# на сервере (иначе пустые — pg_dump берёт локального пользователя и даёт «role root does not exist»).
backup-db:
	ssh $(SERVER) 'cd $(REMOTE_DIR) && \
		mkdir -p backups/db && \
		docker compose --env-file ./.env exec -T db sh -c '"'"'pg_dump -U "$$POSTGRES_USER" "$$POSTGRES_DB" > /tmp/$(BACKUP_NAME).sql'"'"' && \
		docker compose --env-file ./.env exec -T db sh -c '"'"'gzip -f /tmp/$(BACKUP_NAME).sql'"'"' && \
		docker compose --env-file ./.env cp db:/tmp/$(BACKUP_NAME).sql.gz backups/db/$(BACKUP_NAME).sql.gz && \
		docker compose --env-file ./.env exec -T db sh -c '"'"'rm -f /tmp/$(BACKUP_NAME).sql.gz'"'"' && \
		ls -lh backups/db/$(BACKUP_NAME).sql.gz'
	@echo "✅  Backup создан: $(REMOTE_DIR)/backups/db/$(BACKUP_NAME).sql.gz"

# ── 7. Telegram: актуализация карточек согласований по ID заявок (на сервере) ─
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

# ── 8. Откат production ──────────────────────────────────────────────────────
rollback:
	@echo "⚠️  Откат production на предыдущий образ..."
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker tag n8n-backend_v2:previous n8n-backend_v2:latest 2>/dev/null && \
		docker tag n8n-frontend_v2:previous n8n-frontend_v2:latest 2>/dev/null && \
		docker compose --env-file ./.env up -d --no-deps backend_v2 frontend_v2"
	@echo "✅  Откат выполнен."

# ── 9. Локальный docker compose (docker-compose.local.yml) ────────────────
local-up:
	docker compose -f docker-compose.local.yml --env-file .env.local up -d --build

local-down:
	docker compose -f docker-compose.local.yml --env-file .env.local down

local-logs:
	docker compose -f docker-compose.local.yml --env-file .env.local logs -f --tail=200
