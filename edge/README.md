# Edge Traefik (kolberg)

Единственная точка входа сервера: порты 80/443 и сертификаты Let's Encrypt
для всех проектов. Проекты подключаются к внешней сети `traefik-public` и
описывают роутеры Docker-лейблами с `tls.certresolver=mytlschallenge`; сам
edge ничего не знает о проектах.

Раньше Traefik был сервисом внутри проекта n8n (образ `traefik` без тега,
сеть принадлежала n8n). Теперь это отдельный проект `edge`:

- зафиксирована мажорная версия (`traefik:v3`): `pull` приносит исправления
  v3.x, переход на v4 — только осознанной сменой тега;
- том `n8n_traefik_data` (acme.json) сохранил старое имя и подключён как
  external — ни один сертификат перевыпускать не пришлось;
- сеть называлась `n8n_traefik-public`; в 2026-10 её переименовали в
  `traefik-public` (см. ниже);
- редирект `https://<sub>.kolberg.uz/ → /app` переехал на `frontend_v2`
  (он использует тот же `TRAEFIK_FRONTEND_HOST_RULE`).

## Обычная работа

```bash
cd ~/n8n/edge
docker compose ps
docker compose logs --since 10m traefik
```

Обновление (в пределах v3 — без правки файла; на v4 — сначала поменять тег):
`./smoke.sh > /tmp/before.txt && docker compose pull && docker compose up -d && ./smoke.sh | diff /tmp/before.txt -`.

## Сеть `traefik-public` и проекты с syrop

До 2026-10 сеть называлась `n8n_traefik-public`. Docker не умеет
переименовывать сети, поэтому её заменили новой: `docker network create
traefik-public`, затем каждый стек (edge, n8n, bot, kolberg-mcp,
whatsapp-api, medical_portal) пересоздан с новым именем сети, после чего
старая сеть удалена. Новое имя совпадает с тем, что ждут проекты с syrop.

Проекты с syrop (horeca-demo, bubbleking, about-muse-warehouse,
marketing_signage, recipebook) переносит `edge/migrate-from-syrop.sh`
(запускается с рабочей машины, где есть ssh-алиасы `syrop` и `kolberg`):

- `prepare` копирует каталог проекта, меняет в его compose-файлах
  `certresolver` `letsencrypt` → `mytlschallenge` (на syrop был HTTP-01
  резолвер с таким именем) и собирает образы;
- `cutover` останавливает проект на syrop и переносит тома со сверкой числа
  файлов и байтов;
- после смены A-записи `start` поднимает проект и ждёт валидный сертификат.

На syrop остаются остановленные контейнеры и тома — копия для `rollback`.

## Однократный перенос из проекта n8n

Простой всех сайтов — несколько секунд (шаг 4).

1. Снимок до (с любой машины):
   ```bash
   ./edge/smoke.sh > /tmp/edge_before.txt
   ```
2. Подготовка на сервере (без простоя):
   ```bash
   cd ~/n8n
   git apply --check edge.patch && git apply edge.patch
   grep '^SSL_EMAIL=' .env > edge/.env
   cd edge && docker compose config -q && docker compose pull
   ```
3. Перенести редирект на `frontend_v2` (простой `/app` — секунды):
   ```bash
   cd ~/n8n && docker compose --env-file ./.env up -d --no-deps frontend_v2
   ```
   Пока старый traefik жив, редирект описан дважды (у него и у
   `frontend_v2`) с одинаковым правилом — оба ведут на `/app`, это безопасно.
4. Переключение (простой — секунды):
   ```bash
   docker stop traefik && docker rm traefik && cd ~/n8n/edge && docker compose up -d
   ```
5. Проверка:
   ```bash
   ./edge/smoke.sh | diff /tmp/edge_before.txt - && echo SAME
   docker logs traefik --since 5m 2>&1 | grep -iE 'error|acme' | head
   ```
6. Коммит на сервере:
   ```bash
   cd ~/n8n && git add docker-compose.yml edge && git commit -m "infra: move edge Traefik out of the n8n project"
   ```
   `edge/.env` не коммитится (`.env` в `.gitignore`).

### Откат

```bash
cd ~/n8n/edge && docker compose down          # сеть и том external — не удаляются
cd ~/n8n && git checkout -- docker-compose.yml # или git revert, если уже закоммичено
docker compose --env-file ./.env up -d --no-deps traefik frontend_v2
```

Старый образ `traefik:latest` остаётся локально, `up` его не перекачивает.
