# Makefile: upload everything in this folder to kolberg:~/n8n/
SERVER     := kolberg
REMOTE_DIR := ~/n8n

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

.PHONY: deploy dry-run clean-remote

deploy:
	rsync -av --omit-dir-times $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/

dry-run:
	rsync -avzn --delete $(EXCLUDES) ./ $(SERVER):$(REMOTE_DIR)/

clean-remote:
	ssh $(SERVER) "rm -rf $(REMOTE_DIR)/*"


back:
	rsync -avz --progress --omit-dir-times ${EXCLUDES} $(SERVER):$(REMOTE_DIR)/backend ./
