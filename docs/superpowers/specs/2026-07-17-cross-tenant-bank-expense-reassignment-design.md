# Кросс-тенантное переприсвоение банковских расходов (lemonfit → lemonhavo)

- **Дата:** 2026-07-17
- **Ветка:** `dev/new-endpoints`
- **Статус:** одобрено к реализации

## Контекст и проблема

Один общий расчётный счёт обслуживает два тенанта: `lemonfit` (владелец счёта — выписки
импортируются только сюда) и `lemonhavo` (заявки на часть этих же транзакций создаются
здесь). Из-за строгой тенантной изоляции данных это даёт две симметричные проблемы:

- в `lemonfit` — «жёлтые» строки: банковский расход без заявки (заявка на самом деле в
  `lemonhavo`);
- в `lemonhavo` — «красные» строки: оплаченная заявка (`status=PAYED`) без связанного
  расхода (расход на самом деле сидит в `lemonfit`).

Ранее прорабатывался подход с копированием заявок между тенантами (поля `source_tenant` /
`source_request_id` / `external_matched_tenant` на `Request`, отдельные n8n-эндпоинты на
импорт копии и обратный callback). Руководитель этот подход отклонил. Ветка с этой
реализацией в `main` не мержилась; `dev/new-endpoints` пересоздана заново от актуального
`main`, старый код отсутствует.

## Цель

Сразу после импорта выписки в `lemonfit`, для каждого банковского расхода, у которого нет
соответствующей заявки в `lemonfit`, проверить — есть ли соответствующая PAYED-заявка в
`lemonhavo`. Если да — **перенести сам расход** (`BankExpense`) в `lemonhavo` (с
корректировкой `wallet`/`vendor`, которые тоже тенант-скоуплены) и сразу же связать его с
найденной заявкой (`expense_ref_id`/`expense_ref_target`), чтобы красная строка в
`lemonhavo` исчезла в том же запросе — без второго шага, без промежуточного состояния.
Если совпадений нет ни в одном тенанте — расход остаётся в `lemonfit` как есть.

### Non-goals

- `BankRevenue` (входящие) — только `BankExpense` (исходящие), как и было явно
  сформулировано в задаче.
- Обобщённый механизм на N тенантов — жёстко на пару `lemonfit`/`lemonhavo`, как и текущий
  сценарий. Обобщение — отдельная задача, если понадобится.
- Никаких новых полей моделей и миграций не требуется — `BankExpense.tenant/wallet/vendor`
  и `Request.expense_ref_id/expense_ref_target` уже существуют.

## Архитектура

```
n8n: импорт выписки в lemonfit
        │
        ▼
POST /api/n8n/bank/expenses/batch/        (существующий, без изменений)
        │  (существующий relink: _relink_requests_to_bank_expenses уже
        │   проставляет expense_ref_id для расходов, у которых заявка
        │   нашлась в самом lemonfit)
        ▼
POST /api/n8n/bank/expenses/reassign-unmatched/     ← НОВЫЙ, один вызов на весь батч
        │
        │  для каждого BankExpense в lemonfit, у которого до сих пор
        │  нет связанной заявки (expense_ref_target='bank' не проставлен):
        │
        ├─ ищем в lemonhavo: Request(tenant=lemonhavo, status=PAYED,
        │     payment_type in {Перечисление, Пополнение},
        │     expense_id=doc_no, expense_year=expense_year, amount=debit_turnover)
        │
        ├─ не найдено / неоднозначно (0 или >1) → расход остаётся в lemonfit, пропуск
        │
        └─ найдено ровно одно совпадение →
              wallet = get_or_create_bank_wallet(tenant=lemonhavo)      (существующий helper)
              vendor = get_or_create_vendor_by_account_number(          (новый, по аналогии)
                          tenant=lemonhavo, source_vendor=expense.vendor)
              UPDATE BankExpense: tenant=lemonhavo, wallet=wallet, vendor=vendor
              UPDATE Request:     expense_ref_id=<expense.pk>,
                                  expense_ref_target=EXPENSE_REF_TARGET_BANK
```

Существующая бизнес-логика matching'а (`payment_type`/`doc_no`/`expense_year`/`amount`,
`status=PAYED`) не дублируется отдельным SQL или в n8n — используется тот же принцип, что
уже применяется в `_relink_requests_to_bank_expenses` (тот же файл,
`apps/modules/n8n_integration/views.py`).

## Backend: новый endpoint

`POST /api/n8n/bank/expenses/reassign-unmatched/`, вызывается на хосте `lemonfit`, тот же
`_N8nBaseView` / `N8nIntegrationTokenOnlyAuthentication`, что и у остальных n8n-эндпоинтов
(`apps/modules/n8n_integration/views.py`) — без нового способа аутентификации.

**Тело запроса:**
```json
{ "other_tenant": "lemonhavo" }
```

**Валидация:**
- `other_tenant` обязателен, резолвится через
  `Tenant.objects.filter(subdomain=..., is_active=True).first()`;
- 400, если не найден;
- 400, если равен текущему (хост-)тенанту.

**Обработка** (каждый переносимый расход — в своей `transaction.atomic()`, чтобы сбой на
одном не откатывал уже обработанные):

1. Кандидаты — **все** `BankExpense` в `lemonfit`, у которых ещё нет привязанной заявки в
   `lemonfit` (нет `Request(tenant=lemonfit, expense_ref_target='bank', expense_ref_id=<pk>)`),
   независимо от даты импорта — не только расходы из текущего батча. Так вызов идемпотентен
   и самовосстанавливается: если расход не нашёл пару в прошлый раз (например, заявка в
   `lemonhavo` появилась позже), следующий вызов эндпоинта его подхватит без отдельного
   отслеживания «что именно было в этом батче» на стороне n8n.
2. Для каждого — поиск в `other_tenant`:
   `Request.objects.filter(tenant=other_tenant, payment_type__in=(TRANSFER, TOPUP), status=PAYED, expense_id=doc_no, expense_year=expense_year, amount=debit_turnover)`.
   Если не ровно одно совпадение — пропуск, расход остаётся в `lemonfit`.
3. При ровно одном совпадении:
   - `wallet = get_or_create_bank_wallet(tenant=other_tenant)` — существующий helper
     (`apps/modules/wallets/resolution.py`), идемпотентен (уникальность `BankAccount` на
     тенант и `Wallet` на `bank_account`).
   - `vendor` — новый небольшой helper, ищет/создаёт `Vendor` в `other_tenant` по
     `account_number` исходного `expense.vendor` (по аналогии с уже существующим паттерном
     upsert-вендора по `account_number` в `N8nVendorImportSerializer`). Если у исходного
     расхода вендора нет или нет `account_number` — `vendor=None`, без ошибки.
   - `BankExpense.objects.filter(pk=expense.pk).update(tenant=other_tenant, wallet=wallet, vendor=vendor)`.
   - `Request.objects.filter(pk=matched_request.pk).update(expense_ref_id=expense.pk, expense_ref_target=Request.EXPENSE_REF_TARGET_BANK)`
     (через `.update()`, не `.save()` — чтобы не задеть побочные эффекты `Request.save()`,
     как и в остальном коде проекта).

**Ответ:** `{"reassigned": [{"expense_id": ..., "request_id": ..., "tenant": "lemonhavo"}, ...], "count": N}`.
Информационный, воркфлоу не обязан на нём ветвиться.

## n8n: изменение воркфлоу

Один новый HTTP-нод в существующем воркфлоу импорта выписки `lemonfit`, сразу после
текущего нода отправки батча банковских расходов (`bank/expenses/batch/`). Вызывает новый
эндпоинт на хосте `lemonfit` с телом `{"other_tenant": "lemonhavo"}`, тот же credential
(Header Auth), что и у остальных нодов этого воркфлоу. Без разветвления/циклов по items —
весь батч обрабатывается на бэкенде за один вызов.

## Тестирование

- Ровно одно совпадение в `lemonhavo` → расход и вендор перенесены, wallet у lemonhavo
  создан/переиспользован, заявка получила `expense_ref_id`/`expense_ref_target`.
- Совпадение уже есть в `lemonfit` → расход не трогается (уже «свой»).
- Совпадений нет нигде → расход остаётся в `lemonfit` без изменений.
- Неоднозначность (2+ совпадения в `lemonhavo`) → расход не переносится (безопасный no-op).
- У исходного расхода нет вендора / нет `account_number` → перенос происходит, `vendor=None`,
  без ошибки.
- Идемпотентность `get_or_create_bank_wallet` — два перенесённых расхода одного тенанта не
  создают два `BankAccount`/`Wallet`.
- Валидация `other_tenant`: отсутствует / неизвестен / равен хост-тенанту → 400.

Прогон — исключительно через CI (`Backend Tests`), локальный запуск тестов агентом запрещён
правилами проекта.

## Риски

- Тело `Vendor.account_number` для расхода без вендора может быть `None` — helper обязан
  обрабатывать это без исключения (см. тест выше).
- `wallet` у `BankExpense` — `PROTECT`, не `null`; без корректировки `wallet` при переносе
  тенанта осталась бы рассинхронизация `wallet.tenant != expense.tenant` — явно
  предотвращается шагом с `get_or_create_bank_wallet`.
- Matching-правило (payment_type/doc_no/amount/expense_year/status) не должно
  переопределяться отдельно от `_relink_requests_to_bank_expenses` — держать в одном месте
  или явно переиспользовать существующую функцию, а не копировать условие.

## Ограничения

- Новых миграций не требуется.
- Работа только над эндпоинтом в `n8n_integration` + workflow-нодом; ревёрт старого
  (отклонённого) подхода не требуется — в этой ветке его уже нет.
