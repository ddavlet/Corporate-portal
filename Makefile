# Makefile: upload everything in this folder to kolberg:~/n8n/
SERVER     := kolberg
REMOTE_DIR := ~/n8n
.DEFAULT_GOAL := main

# Files/folders to exclude from upload
EXCLUDES := \
	--exclude .git/ \
	--exclude .gitignore \
	--exclude Makefile \
	--exclude .DS_Store \
	--exclude node_modules/ \
	--exclude __pycache__/ \
	--exclude "*.pyc" \
	--exclude env \
	--exclude .env

.PHONY: main deploy-files migrate-v2 deploy-rebuild-v2

main: deploy-files

deploy-files:
	rsync -av --omit-dir-times $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/

migrate-v2:
	ssh $(SERVER) "cd $(REMOTE_DIR) && docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate && docker compose --env-file ./.env restart backend_v2"

deploy-rebuild-v2:
	$(MAKE) deploy-files
	ssh $(SERVER) "cd $(REMOTE_DIR) && docker compose --env-file ./.env up -d --build backend_v2 frontend_v2 && docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate && docker compose --env-file ./.env restart backend_v2"
