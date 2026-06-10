#!/bin/bash
set -euo pipefail

CRONTAB_SRC=/app/cron/crontab
if [[ ! -f "$CRONTAB_SRC" ]]; then
  echo "Missing cron schedule: $CRONTAB_SRC" >&2
  exit 1
fi

cp "$CRONTAB_SRC" /etc/cron.d/kolberg
chmod 0644 /etc/cron.d/kolberg

exec cron -f
