# Нерешённые проблемы безопасности

Аудит: 2026-07-23 · сервер `ubuntu-1cpu-1gb-de-fra1` + репозиторий Kolberg.  
Статус: открыто, пока пункт не закрыт явно (дата + коммит/действие).

Легенда приоритета: **P1** — сделать в первую очередь · **P2** — ближайший спринт · **P3** — планово · **P4** — бэклог / низкий риск.

---

## 1. Adminer доступен из интернета
- **Приоритет:** P1
- **Где:** `docker-compose.yml` → `adminer`, хост `database.kolberg.uz`
- **Суть:** UI Adminer открыт через Traefik без basicAuth / IP allowlist / VPN. Вход по логину/паролю Postgres есть, но форма брутфорса к прод-БД публична.
- **Что сделать:** убрать public-router или ограничить VPN / Traefik basicAuth + IP allowlist.

## 2. Веб-UI wg-easy слушает `:51821` на всех интерфейсах
- **Приоритет:** P1
- **Где:** `docker-compose.yml` → `wg-easy` (`network_mode: host`), порт TCP 51821
- **Суть:** пароль (`PASSWORD_HASH`) есть. UDP **51820** (WireGuard) снаружи нужен клиентам; TCP **51821** (админка) — нет.
- **Что сделать:** закрыть 51821 firewall’ом или bind на localhost; заходить по SSH-туннелю / уже через VPN.

## 3. Telegram bot token закоммичен в тестовый/seed код
- **Приоритет:** P2
- **Где:** `backend_v2/apps/tenants/management/commands/seed_test_data.py`, `backend_v2/test_telegram_unified.py`, `test_telegram_unified.py`
- **Суть:** литерал `TEST_TENANT_BOT_TOKEN` (и fallback в unified-тестах). Предназначен для тестов, но живой токен в git history = риск угона бота, если токен когда-либо был настоящим.
- **Что сделать:** отозвать в BotFather при сомнении; убрать литерал; брать только из env (`SEED_TEST_TELEGRAM_BOT_TOKEN`); в коде — явный fake.

## 4. ~~Legacy public webhook investments approvals~~ — закрыто 2026-07-23
- **Было:** `POST /api/investments/approvals/webhook/` публично через Traefik (`AllowAny`).
- **Сделано:** публичный route удалён из `investments/urls.py`. Обработчик `InvestmentApprovalWebhookView` вызывается только из внутреннего `/api/messaging-gateway/webhook/` (tg-gateway, исключён из Traefik). Тесты переведены на messaging-gateway; регрессия `test_legacy_public_investments_approval_webhook_is_removed` (404).

## 5. Bot token в path URL tg-gateway webhook
- **Приоритет:** P2
- **Где:** `tg-gateway/main.py` → `POST /v1/messaging/webhook/{bot_token}`
- **Суть:** токен в URL может утекать в access-логи / прокси. Нет проверки `X-Telegram-Bot-Api-Secret-Token`.
- **Что сделать:** opaque path id + `secret_token` при `setWebhook` и валидация заголовка.

## 6. SSRF через FileGatewayView
- **Приоритет:** P2
- **Где:** `backend_v2/apps/modules/requests/views.py` → `FileGatewayView`
- **Суть:** аутентифицированный пользователь может передать абсолютный `http(s)://` URL; бэкенд ходит туда с tenant file-gateway Bearer. Нет allowlist хостов / блокировки private IP.
- **Что сделать:** allowlist upstream; запрет private/link-local; предпочтительно path-only ссылки, резолв на сервере.

## 7. SSH: fail2ban выключен, PermitRootLogin yes
- **Приоритет:** P2
- **Где:** сервер (`sshd`, fail2ban)
- **Суть:** `PasswordAuthentication` фактически **no** (хорошо). Идёт постоянный брутфорс `Invalid user`. fail2ban inactive. В конфиге `PermitRootLogin yes`.
- **Что сделать:** включить fail2ban (sshd jail); `PermitRootLogin no` (или `prohibit-password`); синхронизировать `sshd_config` с effective `sshd -T`.

## 8. Права на `.env` слишком открытые
- **Приоритет:** P2
- **Где:** сервер `~/n8n/.env` (644), `~/whatsapp-api/.env` / `~/kolberg-mcp/.env` (664)
- **Суть:** секреты читаемы шире, чем нужно.
- **Что сделать:** `chmod 600` на все `.env` с секретами.

## 9. Нет host firewall (UFW)
- **Приоритет:** P3
- **Где:** сервер
- **Суть:** публично слушаются 22, 80, 443, 51821 (+ UDP 51820). UFW не настроен; опора на провайдера/Docker.
- **Что сделать:** UFW/cloud firewall: только 22 (по желанию restrict), 80/443, UDP 51820; 51821 — нет.

## 10. JWT access/refresh в `localStorage`
- **Приоритет:** P3
- **Где:** `frontend_v2/src/lib/api.ts`, `frontend_v2/src/ui/auth.tsx`
- **Суть:** XSS = кража сессии. `dangerouslySetInnerHTML` в app не найден (плюс), но поверхность остаётся.
- **Что сделать:** httpOnly Secure cookies + CSRF, либо усилить CSP / XSS-поверхность.

## 11. OTP генерируется через `random`, не `secrets`
- **Приоритет:** P3
- **Где:** `backend_v2/apps/accounts/views_otp.py`
- **Суть:** `random.randint` не CSPRNG. Rate limit есть.
- **Что сделать:** `secrets.randbelow` / `secrets.choice`.

## 12. Messaging-gateway callbacks без shared secret
- **Приоритет:** P3
- **Где:** `TelegramApprovalWebhookView` / events — `AllowAny`; изоляция = Docker network
- **Суть:** с интернета путь закрыт Traefik-исключением; при компрометации другого контейнера — можно дергать callbacks.
- **Что сделать:** shared secret или mTLS между tg-gateway и Django.

## 13. Traefik: docker.sock (+ n8n debug logs)
- **Приоритет:** P3
- **Где:** `docker-compose.yml` → `traefik` (`/var/run/docker.sock:ro`); n8n `N8N_LOG_LEVEL=debug`
- **Суть:** socket RO, но RCE Traefik ≈ host. Traefik `--log.level` уже **WARN** (2026-07-23). Остаётся n8n debug и опционально socket-proxy.
- **Что сделать:** socket-proxy; `N8N_LOG_LEVEL=warn` (или info) в prod.
- **Частично:** Traefik log level DEBUG → WARN.

## 14. Bind-mount исходников backend в production
- **Приоритет:** P3
- **Где:** `docker-compose.yml` → `backend_v2`, `backend_cron`: `./backend_v2:/app`
- **Суть:** запись на хост = код в контейнере.
- **Что сделать:** деплой только из immutable image layers, без source bind mount в prod.

## 15. MCP: открытая dynamic client registration
- **Приоритет:** P3
- **Где:** `backend_v2/apps/mcp_server/` — `/mcp/register`
- **Суть:** клиенты могут регистрировать произвольные `redirect_uris` (`token_endpoint_auth_method=none`). Логин всё равно нужен; риск phishing/open-redirect на OAuth callback.
- **Что сделать:** ограничить redirect URI; auth на registration или allowlist.

## 16. Закоммичен `.env.local`
- **Приоритет:** P4
- **Где:** `.env.local` (в `.gitignore` только `.env`)
- **Суть:** локальные секреты/DEBUG в репозитории.
- **Что сделать:** добавить `.env.local` в `.gitignore`; убрать из индекса; оставить `.env.example` без секретов.

## 17. ~~Hardcoded Django `SECRET_KEY` в legacy `backend/`~~ — закрыто 2026-07-23
- **Было:** insecure `SECRET_KEY` в `backend/config/settings.py`; сервис в compose уже был закомментирован.
- **Сделано:** каталог `backend/` удалён из репозитория; закомментированный service `backend` и nginx `staticfiles` (legacy `/static/` для старого портала) убраны из `docker-compose.yml`.

## 18. Небезопасные defaults `SECRET_KEY` / `ALLOWED_HOSTS` в коде
- **Приоритет:** P4
- **Где:** `backend_v2/config/settings.py`, defaults в compose
- **Суть:** fallback `dev-only-change-me`; пустой `DJANGO_ALLOWED_HOSTS` → `["*"]`. На prod сейчас заданы явно (`DJANGO_DEBUG=false`, hosts перечислены) — ок, но fail-open в коде остаётся.
- **Что сделать:** fail-fast в production, если secret default / hosts пустые.

## 19. Неполное pin’инг зависимостей backend
- **Приоритет:** P4
- **Где:** `backend_v2/requirements.txt`
- **Суть:** часть пакетов без точных pin (DRF, simplejwt и др.).
- **Что сделать:** pin exact versions; Dependabot/Renovate + CVE review.

## 20. Публичные n8n UI / webhook routes
- **Приоритет:** P4
- **Где:** `dev.kolberg.uz`, tenant `/webhook/`, `/form/`
- **Суть:** ожидаемо для n8n; риск = слабый auth n8n или неавторизованные workflow webhooks + debug logging.
- **Что сделать:** жёсткий auth n8n; auth на чувствительных webhook; убрать debug log в prod.

---

## Уже в порядке (не в бэклоге фикса)

- SSH password authentication фактически выключен (`sshd -T`).
- Postgres / n8n / Django / WhatsApp порты не published на хост (кроме Traefik 80/443).
- `DJANGO_DEBUG=false`, явный `DJANGO_ALLOWED_HOSTS` на prod.
- n8n integration: token + `secrets.compare_digest`.
- Telegram WebApp / Login Widget: HMAC с bot token перед JWT.
- HSTS на Traefik для публичных HTTPS-хостов.
- **#4** Legacy public investments approvals webhook снят с `/api` (только messaging-gateway).
- **#17** Legacy `backend/` удалён из репозитория.

---

## Закрыто

### 4. Legacy public webhook investments approvals — 2026-07-23
Публичный `POST /api/investments/approvals/webhook/` удалён. Callbacks `inv_` / `invp_` только через внутренний messaging-gateway.

### 17. Legacy `backend/` removed — 2026-07-23
Каталог `backend/` и compose-сервисы legacy Django + `staticfiles` удалены. Остаётся только `backend_v2`.

---

## Как закрывать пункт

1. Исправить (код / сервер).
2. В этом файле: перенести в секцию «Закрыто» или вычеркнуть с пометкой `закрыто YYYY-MM-DD — <ссылка/коммит/команда>`.
3. Для код-фиксов — тест по правилам проекта + CI.
