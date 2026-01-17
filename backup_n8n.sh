docker compose exec -u node n8n n8n export:workflow  --backup --pretty --separate  --decrypted --output=/home/node/backup/workflows   --includeExecutionHistoryDataTables=true

docker compose exec -u node n8n n8n export:credentials --backup --output=/home/node/backup/credentials --decrypted

docker compose cp n8n:/home/node/backup /opt/backups/n8n/backup-$(date +%F-%H%M)
