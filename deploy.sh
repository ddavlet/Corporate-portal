#!/bin/bash
set -e                    # если любая команда упала — стоп, не идём дальше

DEPLOY_AT="${1:-}"
DEPLOY_RUN_TESTS="${DEPLOY_RUN_TESTS:-1}"
DEPLOY_TEST_PATH="${DEPLOY_TEST_PATH:-apps}"

if [ -n "$DEPLOY_AT" ]; then
  if [[ ! "$DEPLOY_AT" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    echo "Неверный формат времени: '$DEPLOY_AT'. Используй HH:MM"
    exit 1
  fi

  sleep_seconds=$(python3 - "$DEPLOY_AT" <<'PY'
import datetime
import sys

hh, mm = map(int, sys.argv[1].split(":"))
now = datetime.datetime.now()
target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
if target <= now:
    target += datetime.timedelta(days=1)
print(int((target - now).total_seconds()))
PY
)
  echo "Ожидание до $DEPLOY_AT (через ${sleep_seconds} сек.) перед деплоем..."
  sleep "$sleep_seconds"
fi

cd ~/n8n                  # переходим в папку проекта

git pull                  # скачиваем новый код с GitHub

docker compose --env-file ./.env build frontend_v2 tg-gateway backend_cron
                          # пересобираем образы frontend, tg-gateway и backend_cron
                          # backend_v2 (web) пропускаем — код монтируется через bind mount

docker compose --env-file ./.env up -d --no-deps backend_v2
                          # пересоздаём контейнер бека — подхватывает новые env-переменные из .env

docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate
                          # применяем новые миграции к БД

docker compose --env-file ./.env up -d --no-deps backend_cron
                          # планировщик management-команд; живёт отдельно от web-процесса

docker compose --env-file ./.env up -d --no-deps frontend_v2 tg-gateway
                          # перезапускаем frontend_v2 и tg-gateway с новыми образами
                          # --no-deps = не трогать db, n8n и остальные
                          # -d = в фоне

if [ "$DEPLOY_RUN_TESTS" = "1" ]; then
  echo "Запускаю тесты после перезапуска: ${DEPLOY_TEST_PATH}"
  docker compose --env-file ./.env exec -T backend_v2 \
    python manage.py test "$DEPLOY_TEST_PATH" --keepdb -v 2
else
  echo "Тесты после деплоя отключены (DEPLOY_RUN_TESTS=${DEPLOY_RUN_TESTS})"
fi
