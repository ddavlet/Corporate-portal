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

**Техническая поправка после сверки с кодом:** `_N8nBatchBaseView.post()`
(`apps/modules/n8n_integration/views.py:472`) требует, чтобы `request.data` было
JSON-**массивом** (`[item1, item2, ...]`), а не объектом-обёрткой — добавить
`account_no`/`mfo` «в тело батча» физически некуда без ломающего изменения контракта.
Вместо этого — **query-параметры URL** батч-вызова: `?our_account_no=...&our_mfo=...`.
Имена намеренно отличаются от уже существующего построчного поля `account_no` в
`BankExpenseSerializer`/`BankRevenueSerializer` (там это счёт **контрагента**), чтобы не
создавать двусмысленности.

```
n8n: парсинг файла выписки → account_no/mfo "нашего" счёта уже есть в файле
        │
        ▼
POST /api/n8n/bank/expenses/batch/?our_account_no=...&our_mfo=...
[ {item1}, {item2}, ... ]     ← тело батча не меняется, остаётся массивом
        │
        ▼
_N8nBatchBaseView._item_request() уже копирует base_request.GET на каждый item
(views.py:467) — доп. код в батч-обёртках не нужен, значения долетают до каждого
элемента батча автоматически, без изменения тела запроса и без правок
N8nBankExpenseBatchUpsertView/N8nBankRevenueBatchUpsertView.
        │
        ▼
N8nBankExpenseImportSerializer.validate() / N8nBankRevenueImportSerializer.validate()
(n8n_integration/serializers.py) читают our_account_no/our_mfo из
self.context["request"].GET и, если в самом item нет явного wallet_id
(attrs.get("wallet") is None), резолвят
attrs["wallet"] = get_or_create_bank_wallet_for_account(tenant, account_no, mfo)
до вызова super().validate() — дальше существующая цепочка
BankExpenseSerializer/BankRevenueSerializer.validate() →
assign_wallet_for_bank_movement → resolve_wallet_for_bank(wallet_id=attrs["wallet"].pk)
отрабатывает как для explicit wallet_id, БЕЗ изменений в bank_expenses/serializers.py,
wallets/serializer_integration.py и wallets/resolution.resolve_wallet_for_bank.
        │
        ▼
Query-параметры не переданы (старые интеграции) → цепочка не меняется,
assign_wallet_for_bank_movement резолвит через get_or_create_bank_wallet(tenant)
— счёт по умолчанию, см. ниже.
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

Правка: `get_or_create_bank_wallet` сначала ищет `BankAccount.objects.filter(tenant=tenant,
is_default=True).first()`. Если не найден — **самовосстанавливается лениво**, без отдельной
data-миграции: делает `get_or_create(tenant=tenant, account_no="", mfo="", defaults={...,
"is_default": True})`; если находит уже существующую (для всех текущих тенантов — это их
единственный сегодняшний `BankAccount`, у него `account_no=""`/`mfo=""` по дефолту) — просто
проставляет ей `is_default=True` при первом обращении. Схема `is_default` (`default=False`
на уровне поля) — обычная **схемная** миграция (`make makemigrations` сам её сгенерирует по
diff модели: новое поле + замена constraint), без ручного `RunPython`. Один раз, при первом
после миграции обращении к `get_or_create_bank_wallet` для тенанта — промоутит его текущий
единственный счёт в `is_default=True`; повторные вызовы уже находят его напрямую.

## Резолюция (`apps/modules/wallets/resolution.py`)

Новая функция, не меняющая существующую:

```python
def get_or_create_bank_wallet_for_account(*, tenant, account_no, mfo="") -> Wallet:
    account_no = (account_no or "").strip()
    mfo = (mfo or "").strip()
    ba, _ = BankAccount.objects.get_or_create(
        tenant=tenant, account_no=account_no, mfo=mfo,
        defaults={"label": account_no},
    )
    w, _ = Wallet.objects.get_or_create(
        bank_account=ba,
        defaults={"tenant": tenant, "wallet_type": Wallet.Type.BANK, "currency": "UZS", "opening_balance": 0},
    )
    return w
```

`resolve_wallet_for_bank`/`assign_wallet_for_bank_movement`/`resolve_wallet_for_cash` и
пр. в `resolution.py`/`serializer_integration.py` **не меняются** — резолюция по
`account_no`/`mfo` происходит только на стороне n8n-сериализаторов (ниже), которые
передают уже готовый `Wallet` как `attrs["wallet"]`, ровно так же, как если бы вызывающий
явно указал `wallet_id`.

## Контракт `/batch/` (`apps/modules/n8n_integration/`)

- Тело запроса (`items`, каждый item) — без изменений полей.
- Новые **query-параметры** URL, опциональные, применяются и к одиночному, и к batch-
  эндпоинту (`bank/expenses/`, `bank/expenses/batch/`, `bank/revenues/`,
  `bank/revenues/batch/`): `our_account_no`, `our_mfo`.
- `N8nBankExpenseImportSerializer.validate()` (`serializers.py:214`, уже переопределён —
  дополняется) и `N8nBankRevenueImportSerializer.validate()` (`serializers.py:262`, новый
  метод) читают эти параметры через `self.context["request"].GET` и заполняют
  `attrs["wallet"]`, если он ещё не задан явным `wallet_id` в самом item.
- Батч-обёртки (`N8nBankExpenseBatchUpsertView`, `N8nBankRevenueBatchUpsertView`) —
  **без изменений кода**: `_N8nBatchBaseView._item_request` уже копирует `base_request.GET`
  в каждый построчный псевдо-запрос, поэтому query-параметры долетают до каждого item
  автоматически.
- Обратная совместимость: вызов без `our_account_no` продолжает резолвиться в счёт по
  умолчанию, как сейчас.

## Тестирование

- Загрузка батча (`?our_account_no=...`) для тенанта без счетов → создаётся `BankAccount`
  (`is_default=False`) и `Wallet`, все item'ы батча привязаны к нему.
- Повторная загрузка с тем же `our_account_no` → используется существующий `Wallet`,
  дубликат `BankAccount` не создаётся.
- Загрузка с другим `our_account_no` того же тенанта → создаётся второй независимый
  `BankAccount`/`Wallet`, первый не затрагивается.
- Явный `wallet_id` в теле конкретного item имеет приоритет над `our_account_no` из query.
- Вызов без `our_account_no` у тенанта с несколькими счетами → резолвится `is_default=True`
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

- `wallet` на `BankExpense`/`BankRevenue` — `on_delete=PROTECT`, **не** `null`
  (`bank_expenses/models.py:39-42,88-91`, подтверждено). Резолюция счёта по умолчанию
  обязана быть надёжной (не кидать исключение) для всех существующих интеграций и для
  исходящих платежей по заявкам, которые ещё не обновлены на передачу `our_account_no`.
- Ленивое самовосстановление `is_default` полагается только на то, что у каждого
  сегодняшнего тенанта ровно один `BankAccount` (гарантирует старый constraint) — НЕ на то,
  что его `account_no`/`mfo` пустые (это поле всегда было редактируемым через существующий
  экран настроек счетов). `get_or_create_bank_wallet` поэтому промоутит любой
  единственный/старейший существующий счёт тенанта в `is_default=True`, а не только счёт с
  пустыми `account_no`/`mfo`.
- Операционный риск до переключения n8n: тенант, у которого сегодня заполнен `account_no`,
  но пуст `mfo` (или наоборот), получит дубликат `BankAccount`, как только n8n начнёт
  присылать оба query-параметра батчу выписок этого тенанта — перед включением
  `our_account_no`/`our_mfo` в n8n-воркфлоу нужно свериться/нормализовать существующие
  `account_no`/`mfo` по каждому тенанту.
- Если у тенанта в будущем понадобится позволить выбирать счёт для исходящих платежей —
  это отдельная задача (см. Non-goals), т.к. требует UI на `frontend_v2` и изменений в
  `requests`.

## Ограничения

- Миграция — только схемная (новое поле `is_default` + замена constraint). На практике
  `make makemigrations` не смог её сгенерировать: сервер видит только уже задеплоенный
  `main`, без git pull/checkout ветки — фиче-ветку он структурно не может увидеть.
  Пользователь дал разовое исключение — `0006_bankaccount_is_default.py` написан вручную
  по образцу автогенератора Django (проверено построчно против `0005_...` и финальной
  модели в финальном ревью ветки); `RunPython`/data-миграция не потребовались.
- Изменения: `wallets/models.py` (модель), `wallets/resolution.py` (новая функция +
  бугфикс `get_or_create_bank_wallet`), `n8n_integration/serializers.py`
  (`N8nBankExpenseImportSerializer`/`N8nBankRevenueImportSerializer.validate()`), плюс
  по итогам финального ревью ветки — `wallets/serializers.py` (`is_default` как
  read-only поле в `BankAccountSerializer`, для наблюдаемости состояния, которое стало
  значимым после фикса резолюции счёта по умолчанию). `bank_expenses`, `requests`,
  `n8n_integration/views.py` — без изменений кода, только регрессионные тесты.
