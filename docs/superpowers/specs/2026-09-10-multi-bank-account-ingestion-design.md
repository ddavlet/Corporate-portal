# Загрузка банковских выписок по нескольким счетам тенанта

- **Дата:** 2026-09-10
- **Ветка:** `dev/multi-bank-account-ingestion`
- **Статус:** одобрено к реализации

## Контекст и проблема

Выписки загружаются через `POST /api/n8n/bank/expenses/batch/` и
`POST /api/n8n/bank/revenues/batch/` (`apps/modules/n8n_integration/urls.py:37-45`,
`views.py:1740,1866`). У тенанта может быть несколько реальных расчётных счетов, но
модель `BankAccount` (`apps/modules/wallets/models.py:30-44`) жёстко ограничена одним
счётом на тенанта:

```python
class Meta:
    constraints = [UniqueConstraint(fields=["tenant"], name="wallets_bankaccount_one_per_tenant")]
```

`Wallet` типа `BANK` привязан к `BankAccount` через `OneToOneField`, поэтому у тенанта
физически не может существовать двух банковских `Wallet`. Поля `account_no`/`mfo` на
`BankAccount` уже существуют, но не заполняются и не используются при загрузке —
докстринг модуля прямо объясняет, что одноимённые поля на `BankExpense`/`BankRevenue`
описывают счёт **контрагента**, не «наш» счёт.

Уточнено с пользователем:
- один вызов `/batch/` — это выписка целиком по **одному** счёту тенанта (без смешения
  счетов внутри батча);
- номер счёта/МФО получателя уже присутствует в файле выписки, значит его можно
  прокинуть в payload — новых внешних данных от n8n не требуется, только доработка
  контракта.

## Цель

Позволить тенанту иметь несколько банковских `BankAccount`/`Wallet`, и резолвить нужный
счёт при загрузке батча по `account_no`+`mfo` из заголовка запроса, автоматически создавая
счёт при первом упоминании.

### Non-goals

- Выбор счёта для **исходящих** платежей по заявкам (`requests`) — вне рамок этой задачи.
  `assign_wallet_for_bank_movement` (`apps/modules/requests/services.py:104-109`) при
  отсутствии явного счёта продолжает резолвить **счёт по умолчанию**, а не предлагает
  пользователю выбор из нескольких — см. раздел «Счёт по умолчанию» ниже.
- UI на `frontend_v2` для управления списком счетов тенанта — не запрашивалось; если у
  `wallets` уже есть экран/список счетов, он и так рассчитан на несколько записей
  (`wallets/views.py:100-101` использует `.filter(tenant=tenant)`, не `.get()`).
- Построчная (per-line) идентификация счёта внутри батча — не нужна, т.к. батч = один счёт.

## Архитектура

```
n8n: парсинг файла выписки → account_no/mfo "нашего" счёта уже есть в файле
        │
        ▼
POST /api/n8n/bank/expenses/batch/  (или /revenues/batch/)
{
  "account_no": "...",       ← НОВОЕ, на уровне батча (не построчно)
  "mfo": "...",               ← НОВОЕ, опционально
  "items": [ ... как сейчас ... ]
}
        │
        ▼
resolve_wallet_for_bank(tenant=tenant, wallet_id=None, account_no=..., mfo=...)
        │
        ├─ account_no передан → get_or_create_bank_wallet_for_account(tenant, account_no, mfo)
        │     ищет BankAccount(tenant, account_no, mfo); нет — создаёт BankAccount+Wallet
        │
        └─ account_no не передан (старые интеграции) → get_or_create_bank_wallet(tenant)
              резолвит счёт по умолчанию (см. ниже), НЕ падает при наличии нескольких счетов
        │
        ▼
wallet передаётся один раз на весь батч в построчный upsert (без изменений построчной логики)
```

## Модель данных (`apps/modules/wallets/models.py`)

Изменить constraint на `BankAccount`, разрешив несколько счетов на тенанта, но не
дублирующих друг друга:

```python
class Meta:
    constraints = [
        UniqueConstraint(fields=["tenant", "account_no", "mfo"], name="wallets_bankaccount_unique_per_account"),
    ]
```

Добавить поле `is_default` (см. ниже), с частичным уникальным индексом:

```python
is_default = models.BooleanField(default=False)

class Meta:
    constraints = [
        UniqueConstraint(fields=["tenant", "account_no", "mfo"], name="wallets_bankaccount_unique_per_account"),
        UniqueConstraint(fields=["tenant"], condition=Q(is_default=True), name="wallets_bankaccount_one_default_per_tenant"),
    ]
```

Это багфикс существующего ограничения (в терминах правил проекта — "исключение:
багфикс в существующем коде допустим, но должен сопровождаться тестом"), а не
переписывание рабочей бизнес-логики; схема `Wallet ↔ BankAccount` (1:1) не меняется.

### Счёт по умолчанию

Найден риск: `get_or_create_bank_wallet` (`apps/modules/wallets/resolution.py:67-71`)
делает `BankAccount.objects.get_or_create(tenant=tenant, ...)` без различающего поля.
При наличии у тенанта >1 `BankAccount` это упадёт с `MultipleObjectsReturned`. Эта
функция — единственный фолбэк, когда счёт явно не указан, и используется в двух местах:
загрузка выписки без `account_no` (обратная совместимость со старыми n8n-воркфлоу) и
`assign_wallet_for_bank_movement` для исходящих платежей по заявкам.

Правка: `get_or_create_bank_wallet` резолвит `BankAccount.objects.get(tenant=tenant,
is_default=True)`; если ни одного `is_default` нет — создаёт первый счёт с
`is_default=True` (поведение как раньше для тенантов с одним счётом). Миграция данных
(через `make makemigrations`/бэкафилл на сервере) помечает существующий единственный
`BankAccount` каждого тенанта как `is_default=True`.

## Резолюция (`apps/modules/wallets/resolution.py`)

Новая функция, не меняющая существующую:

```python
def get_or_create_bank_wallet_for_account(*, tenant, account_no, mfo="", label=""):
    ba, created = BankAccount.objects.get_or_create(
        tenant=tenant, account_no=account_no, mfo=mfo,
        defaults={"label": label or account_no, "is_default": False},
    )
    return get_or_create_wallet_for_bank_account(ba)  # существующий паттерн создания Wallet под BankAccount
```

`resolve_wallet_for_bank` расширяется опциональными `account_no`/`mfo` с приоритетом:
явный `wallet_id` → явный `account_no` → счёт по умолчанию (старое поведение).

## Контракт `/batch/` (`apps/modules/n8n_integration/`)

- `N8nBankExpenseImportSerializer`/`N8nBankRevenueImportSerializer`
  (`serializers.py:214,262`) — без изменений построчно.
- Батч-обёртки `N8nBankExpenseBatchUpsertView`/`N8nBankRevenueBatchUpsertView`
  (`views.py:1740,1866`) — добавить на уровне тела запроса необязательные поля
  `account_no`/`mfo`; при наличии — резолвить `wallet` один раз в начале обработки батча
  через `resolve_wallet_for_bank(tenant=tenant, account_no=..., mfo=...)` и передавать
  результат в построчный upsert так же, как сейчас передаётся `wallet_id` per-line
  (если построчный `wallet_id` тоже присутствует — он имеет приоритет, batch-level
  используется только как дефолт для строк без явного `wallet_id`).
- Обратная совместимость: батч без `account_no` продолжает резолвиться в счёт по
  умолчанию, как сейчас.

## Тестирование

- Загрузка батча с новым `account_no` для тенанта без счетов → создаётся `BankAccount`
  (`is_default=False`) и `Wallet`, строки батча привязаны к нему.
- Повторная загрузка батча с тем же `account_no` → используется существующий `Wallet`,
  дубликат `BankAccount` не создаётся.
- Загрузка второго батча с другим `account_no` того же тенанта → создаётся второй
  независимый `BankAccount`/`Wallet`, первый не затрагивается.
- Батч без `account_no` у тенанта с несколькими счетами → резолвится `is_default=True`
  счёт, без `MultipleObjectsReturned`.
- `assign_wallet_for_bank_movement` (исходящий платёж по заявке) у тенанта с несколькими
  счетами и без явного `wallet_id` → использует `is_default=True` счёт, не падает.
- Реконсиляция (`bank_expense_reconciliation.py`, `card_revenue_reconciliation.py`) —
  регрессионный тест, что matching по `vendor+amount+date` работает одинаково независимо
  от количества счетов тенанта (фильтр по `wallet` там не участвует и не должен
  добавляться).
- Constraint: попытка создать два `BankAccount` с одинаковыми `(tenant, account_no, mfo)`
  → `IntegrityError`; попытка выставить `is_default=True` двум счетам одного тенанта →
  `IntegrityError`.

Прогон — исключительно через CI (`Backend Tests`), локальный запуск тестов агентом
запрещён правилами проекта.

## Риски

- `wallet` на `BankExpense`/`BankRevenue` — не `null` (нужно перепроверить точный
  `on_delete`/nullability при реализации), поэтому резолюция счёта по умолчанию должна
  быть надёжной (не кидать исключение) для всех существующих интеграций, которые ещё не
  обновлены на передачу `account_no`.
- Бэкафилл `is_default=True` для существующих тенантов должен быть частью той же миграции,
  что меняет constraint — иначе между миграциями возможно окно, где ни у одного тенанта
  нет `is_default`-счёта и `get_or_create_bank_wallet` создаёт лишний.
- Если у тенанта в будущем понадобится позволить выбирать счёт для исходящих платежей —
  это отдельная задача (см. Non-goals), т.к. требует UI на `frontend_v2` и изменений в
  `requests`.

## Ограничения

- Миграция — только через `make makemigrations` на сервере, локально не создавать.
- Изменения только в `wallets` (модель, resolution) и `n8n_integration` (batch views);
  `bank_expenses`, `requests` — без изменений кода, только регрессионные тесты.
