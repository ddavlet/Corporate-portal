#!/bin/bash
set -e                    # если любая команда упала — стоп, не идём дальше
cd ~/n8n                  # переходим в папку проекта

git pull                  # скачиваем новый код с GitHub

docker compose --env-file ./.env build backend_v2 frontend_v2
                          # пересобираем образы (новый код попадает в контейнер)

docker compose --env-file ./.env exec -T backend_v2 python manage.py migrate
                          # применяем новые миграции к БД

docker compose --env-file ./.env up -d --no-deps backend_v2 frontend_v2
                          # перезапускаем только backend_v2 и frontend_v2
                          # --no-deps = не трогать db, n8n и остальные
                          # -d = в фоне
			 
