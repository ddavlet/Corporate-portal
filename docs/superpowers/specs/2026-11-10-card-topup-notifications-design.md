# Уведомление о пополнении корпоративной карты (перенос из n8n Neuron)

Дата: 2026-11-10. Статус: утверждено владельцем.

## Что было в n8n
Workflow Neuron «New PAYED request», ветка payment_type «Пополнение»: после оплаты заявки бот слал личное
сообщение (chat 6896564346 = пользователь 18, Уктамов Илхом) «💰 Движение денежных средств … Вид движения:
Пополнение корпоративной карты» с суммой, назначением, получателем, комментарием, категорией, плательщиком,
названием карты и строкой «Остаток на карте». Создание прихода на карту в n8n с 08.2026 не работает — приходы
идут из банковской выписки; в портале их НЕ создаём.

## Решения владельца
- Получатели — выбранные пользователи тенанта, личные сообщения (настраивается). Neuron: Уктамов (user 18).
- Остаток — одной строкой, текущий остаток карты, как в n8n (без учёта этого пополнения).
- Работает одинаково для всех тенантов, включается в настройках.

## Поведение
Когда заявка с payment_type «Пополнение» (`Request.PAYMENT_TYPE_TOPUP`) переходит в PAYED и у тенанта есть активная
настройка с хотя бы одним получателем: каждому активному получателю с `telegram_chat_id` отправляется личное
сообщение (после commit). Повторный PAYED не шлёт повторно (запись на пару заявка+получатель). Ошибка отправки не ломает
оплату: статус FAILED + error + лог. Получатель без telegram_chat_id — SKIPPED с понятной ошибкой.

Текст (HTML, как в n8n и как formatter кассы):
💰 <b>Движение денежных средств</b> / 🆔 ID / 📅 Дата (payed_at, иначе billing_date) / 🔄 Вид движения: Пополнение
корпоративной карты / 💵 Сумма / 📝 Назначение платежа / 👤 Получатель (vendor) / 💬 Комментарий (description) /
💳 Категория / 🏢 Плательщик / 💳 Карта: <название> / 💰 Остаток на карте: <current_balance> <валюта>.
Карта: `request.wallet_ref`, если это кошелёк типа corporate_card; иначе единственный/первый (по id) кошелёк
corporate_card тенанта; если карт нет — строки «Карта» и «Остаток» не выводятся. Остаток —
`wallets.services.wallet_balance_payload`. Название карты — как `display_name` в `balances_for_tenant_channel`.
Пустые поля — «—». Экранировать HTML.

## Реализация
В модуле `cash_desk` новыми файлами (OCP): модели `CardTopupNotifyConfig(tenant OneToOne, is_active, recipients M2M
User, updated_at, updated_by)` и `CardTopupNotification(request FK, recipient FK User, status PENDING/SENT/FAILED/
SKIPPED, error, telegram_message FK как у CashDeskMessage, created_at, updated_at, unique(request, recipient))`;
`card_topup.py` (хук + отправка через `TelegramDispatcher` как в `messaging.py`), `card_topup_formatter.py`,
отдельная регистрация хука в `apps.py`. API `GET/PUT /api/cash-desk/card-topup/config/` (IsTenantAdminOrDirector):
`{is_active, recipient_ids, available_users:[{id, name, has_telegram}]}` — available_users = активные участники тенанта.
Миграции 0004 (схема) и 0005 (seed: Neuron — активная настройка с пользователем 18, если он участник тенанта;
остальным ничего). Admin.
Фронт: блок/виджет «Пополнение корпоративной карты» на странице `CashDeskConfigPage` (новый `CardTopupNotifyWidget.tsx`,
API в `src/lib/cashDeskApi.ts`): переключатель и мультиселект получателей, пометка у тех, кто без Telegram.

## После деплоя
Узлы KK в n8n Neuron уже выключены. Проверить первое пополнение.
