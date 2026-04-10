SERVER     := kolberg
REMOTE_DIR := ~/n8n
.DEFAULT_GOAL := deploy-v2

EXCLUDES := \
	--exclude .git \
	--exclude .cursor \
	--exclude Makefile \
	--exclude .DS_Store \
	--exclude node_modules/ \
	--exclude __pycache__/ \
	--exclude "*.pyc" \
	--exclude env \
	--exclude .env

.PHONY: send-files migrate-v2 makemigrations-v2 deploy-v2 rollback-v2 check-garbage

# --- локальные миграции (только для генерации файлов) ---
makemigrations-v2:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py makemigrations"
	rsync -av --omit-dir-times \
		$(SERVER):$(REMOTE_DIR)/backend_v2/migrations/ \
		./backend_v2/migrations/

# --- отправить файлы ---
send-files:
	rsync -av --omit-dir-times $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/

# --- тегировать текущий образ перед деплоем (для rollback) ---
tag-current:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker tag n8n-backend_v2:latest n8n-backend_v2:previous 2>/dev/null || true && \
		docker tag n8n-frontend_v2:latest n8n-frontend_v2:previous 2>/dev/null || true"

# --- основной деплой v2 ---
deploy-v2: send-files tag-current
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env build backend_v2 frontend_v2 && \
		docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate --check && \
		docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate && \
		docker compose --env-file ./.env up -d --no-deps backend_v2 frontend_v2"

# --- откат если что-то сломалось ---
rollback-v2:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker tag n8n-backend_v2:previous n8n-backend_v2:latest && \
		docker tag n8n-frontend_v2:previous n8n-frontend_v2:latest && \
		docker compose --env-file ./.env up -d --no-deps backend_v2 frontend_v2"

# --- посмотреть что лишнее на сервере ---
check-garbage:
	rsync -avnc --delete --dry-run $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/
