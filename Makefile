SERVER     := kolberg
REMOTE_DIR := ~/n8n
.DEFAULT_GOAL := deploy

.PHONY: deploy makemigrations

deploy:
	ssh $(SERVER) "bash $(REMOTE_DIR)/deploy.sh"

makemigrations:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py makemigrations"
	rsync -av --omit-dir-times \
		$(SERVER):$(REMOTE_DIR)/backend_v2/migrations/ \
		./backend_v2/migrations/
