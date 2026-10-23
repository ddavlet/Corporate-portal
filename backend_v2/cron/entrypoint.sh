#!/bin/bash
set -euo pipefail

CRONTAB_SRC=/app/cron/crontab
if [[ ! -f "$CRONTAB_SRC" ]]; then
  echo "Missing cron schedule: $CRONTAB_SRC" >&2
  exit 1
fi

# cron runs jobs with an empty environment, so POSTGRES_*, DJANGO_* etc. from
# docker-compose never reach manage.py (every job failed with
# "settings.DATABASES is improperly configured"). Snapshot the container env
# into a bash-quoted file; jobs load it via BASH_ENV (see crontab).
CRON_ENV_FILE=/etc/kolberg-cron.env
(umask 077 && export -p > "$CRON_ENV_FILE")

cp "$CRONTAB_SRC" /etc/cron.d/kolberg
chmod 0644 /etc/cron.d/kolberg

exec cron -f
