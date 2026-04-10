SERVER     := kolberg
REMOTE_DIR := ~/n8n
.DEFAULT_GOAL := deploy
TEST_PATH ?= apps.modules.requests.tests
DEPLOY_AT ?=
BRANCH    ?= $(shell git rev-parse --abbrev-ref HEAD)

.PHONY: deploy makemigrations push test

deploy:
	ssh $(SERVER) "bash $(REMOTE_DIR)/deploy.sh $(DEPLOY_AT)"

push:
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo "ERROR: Есть незакоммиченные изменения. Сначала commit."; \
		git status --short; \
		exit 1; \
	fi
	git push origin $(BRANCH)

test:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		git pull --ff-only && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py test $(TEST_PATH) --keepdb -v 2"

makemigrations:
	ssh $(SERVER) "cd $(REMOTE_DIR) && \
		docker compose --env-file ./.env exec -T backend_v2 \
		python manage.py makemigrations"
	rsync -av --omit-dir-times \
		$(SERVER):$(REMOTE_DIR)/backend_v2/migrations/ \
		./backend_v2/migrations/
