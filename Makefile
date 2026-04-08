# Makefile: upload everything in this folder to kolberg:~/n8n/
SERVER     := kolberg
REMOTE_DIR := ~/n8n
.DEFAULT_GOAL := main

# Files/folders to exclude from upload
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

.PHONY: main send-files migrate-v2 deploy-rebuild-v2

main: send-files

send-files:
	rsync -av --omit-dir-times $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/

migrate-v2:
	ssh $(SERVER) "cd $(REMOTE_DIR) && docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate && docker compose --env-file ./.env restart backend_v2"

makemigrations-v2:
	ssh $(SERVER) "cd $(REMOTE_DIR) && docker compose --env-file ./.env exec -T backend_v2 python manage.py makemigrations"
	rsync -av --omit-dir-times $(SERVER):$(REMOTE_DIR)/backend_v2/migrations/ ./backend_v2/migrations/

deploy-rebuild-v2:
	$(MAKE) send-files
	ssh $(SERVER) "cd $(REMOTE_DIR) && docker compose --env-file ./.env up -d --build backend_v2 frontend_v2 && docker compose --env-file ./.env exec -T backend_v2 python manage.py makemigrations && docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate && docker compose --env-file ./.env restart backend_v2"

check-garbage:
	rsync -avnc --delete --dry-run $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/
