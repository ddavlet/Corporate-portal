#!/bin/bash

# Usage:
#   ./upload-n8n.sh <file or directory> [...]
#
# SSH alias "kolberg" is used from your ~/.ssh/config
# Remote directory:               ~/n8n/

SSH_HOST="kolberg"
REMOTE_PATH="~/n8n/"

if [ $# -eq 0 ]; then
  echo "Usage: $0 <file-or-directory> ..."
  exit 1
fi

# Make sure remote directory exists
ssh "$SSH_HOST" "mkdir -p $REMOTE_PATH"

echo "📤 Uploading to $SSH_HOST:$REMOTE_PATH"

for item in "$@"; do
  if [ ! -e "$item" ]; then
    echo "❌ Not found: $item"
    continue
  fi

  echo "➡️  Syncing: $item"
  rsync -avz "$item" "$SSH_HOST:$REMOTE_PATH"
done

echo "✅ Upload complete."
