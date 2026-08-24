# Выплаты ЗП по кассе + справочник сотрудников

## Проблема

Начисление ЗП (`payroll.PayrollDocument`) при включённой настройке "Создавать заявку на оплату при создании начисления" автоматически порождает одну `requests.Request` (payment_type=`Начисление ЗП`) на сумму всего документа. Когда эта заявка проходит согласование до последнего (payment) шага, она сразу переводится в статус `PAYED`, а её `expense_ref` указывает на сам `PayrollDocument` (`EXPENSE_REF_TARGET_PAYROLL`).

Это осознанно: не нужно согласовывать каждую отдельную выплату сотруднику — согласуется весь документ разом. Но следствие: при этом **не создаётся** ни одного `cashier.CashExpense`, то есть фактическая выдача денег из кассы никак не отражается в остатке кассы (`cash_expenses`). Для расходов типа "Наличные" (`PAYMENT_TYPE_CASH`) такой `CashExpense` создаётся отдельным действием (`create_expense_for_request_payment`), а для ЗП — нет и никогда не создавался.

Дополнительно: сотрудник в строке начисления (`PayrollLine.employee`) сейчас — произвольный текст, без справочника. Это мешает надёжно агрегировать "сколько уже выплачено конкретному сотруднику по конкретному начислению" и приводит к разночтениям из-за опечаток/разного написания имени.

## Цель

1. Ввести справочник сотрудников (`payroll.Employee`), обязательный для каждой строки начисления.
2. Дать возможность фиксировать фактическую выплату наличными по строке начисления (по сотруднику), создающую реальный `CashExpense`, — без повторного согласования заявки.
3. Не ломать существующий функционал: n8n-импорт начислений, уже созданные заявки, отчётность по expense compliance.

Вне рамок этой задачи: выплаты ЗП банковским переводом (только касса/наличные), привязка выплаты к нескольким сотрудникам одной транзакцией.

## Часть 1: Справочник сотрудников

### Модель `payroll.Employee`

```python
class Employee(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="employees")
    full_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "payroll_employees"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "full_name"], name="uniq_employee_tenant_full_name"),
        ]
```

Точное совпадение строки (без учёта регистра не делаем — если позже понадобится, добавим отдельно).

### `PayrollLine.employee`: смена типа CharField → FK

Поле остаётся с тем же именем `employee`, но становится обязательным `ForeignKey(Employee, on_delete=models.PROTECT, related_name="payroll_lines")`. `PROTECT`, потому что строка начисления — исторический факт, сотрудника из справочника нельзя удалить, если на него есть ссылки (справочник и не предполагает удаления записей вообще, только точечное редактирование имени при опечатке).

### Миграция (3 фазы, без потери данных)

Прямая смена типа поля с данными в нём не поддерживается один шагом. План:

**Фаза A (схема).** В `models.py`: добавляем модель `Employee`; на `PayrollLine` добавляем временное поле `employee_fk = models.ForeignKey(Employee, null=True, on_delete=models.PROTECT, related_name="payroll_lines")`. Старое `employee = CharField` пока не трогаем. Прогоняем `make makemigrations` — получаем миграцию создания таблицы `Employee` + добавления nullable `employee_fk` на `PayrollLine`.

**Фаза B (дата-миграция, `RunPython`, рукописная).** Идёт следующим номером миграции:
- Для каждого `tenant_id` собрать различные непустые значения `PayrollLine.employee` (`.values_list("tenant_id", "employee").distinct().iterator()`).
- `Employee.objects.get_or_create(tenant_id=tenant_id, full_name=name.strip())` — идемпотентно, ничего не перезаписывает и не удаляет.
- Батчами (`.iterator()` + `bulk_update` или `.update()` по группам `(tenant_id, employee)`) проставить `employee_fk_id` на все совпадающие строки `PayrollLine`.
- `reverse_code` — не восстанавливает текст (он и не удалялся на этом шаге), просто no-op.

**Фаза C (схема, финал).** После проверки, что бэкафилл прошёл (все строки имеют `employee_fk`), в `models.py`: `employee_fk` → `null=False`; старое `employee` (CharField) удаляем; `employee_fk` переименовываем в `employee` (`migrations.RenameField`). Прогоняем `make makemigrations` ещё раз.

Фазы B и C выполняются в отдельных PR/деплоях друг за другом только после того, как предыдущая фаза выкачена и бэкафилл подтверждён на проде (`make showmigrations` + точечная проверка через `execute_sql`, что `employee_fk_id IS NULL` строк нет) — это исключает риск потери данных при сбое посреди процесса.

### n8n-импорт — контракт не меняется

`N8nPayrollLineImportSerializer` продолжает принимать `employee` как строку (ФИО) в JSON. На сервере:

```python
class N8nPayrollLineImportSerializer(serializers.ModelSerializer):
    employee = serializers.CharField(write_only=True)  # перекрывает автогенерируемое FK-поле
    ...
    def create(self, validated_data):
        ...
        employee_name = validated_data.pop("employee").strip()
        employee_obj, _ = Employee.objects.get_or_create(tenant=tenant, full_name=employee_name)
        return PayrollLine.objects.create(document=doc, employee=employee_obj, **validated_data)

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["employee"] = instance.employee.full_name
        ...
```

Аналогично в `update()`. Это ровно то, что просили: "сначала поиск по сотрудникам, если нет — добавить", без изменений на стороне n8n.

### Портал — создание начисления

`PayrollLineCreateSerializer.employee`: было `CharField()`, становится `PrimaryKeyRelatedField(queryset=...)`, queryset фильтруется по тенанту в `__init__` через `context["request"].tenant`. Нельзя сохранить строку начисления без выбора существующего сотрудника.

`create_payroll_document` (`payroll/services.py`) правится точечно: `employee=line_data["employee"]` — теперь это уже `Employee`-инстанс (DRF `PrimaryKeyRelatedField` отдаёт объект), без дополнительной резолюции.

### Чтение (детальный вид документа)

`PayrollLineSerializer.employee`: вместо плоской строки — `{"id": employee.id, "full_name": employee.full_name}` (`SerializerMethodField`), чтобы фронт мог показывать имя и, в перспективе, ссылаться на карточку сотрудника.

### API справочника

- `GET /api/payroll/employees/` — список сотрудников тенанта, поиск по имени, пагинация как у остальных списков (`PortalListViewSetMixin`).
- `POST /api/payroll/employees/create/` — `{"full_name": "..."}`. По образцу пары `PayrollDocumentViewSet` (ReadOnly) + `PayrollDocumentCreateView`.

### Фронтенд

- В форме строки начисления (`PayrollPage.tsx`) поле "сотрудник": `Input` → `Select` с поиском (`showSearch`), обязательное. В выпадающем списке — пункт "+ Добавить сотрудника", открывающий модалку из одного поля (ФИО); после создания сотрудник сразу подставляется в строку.
- Отдельная секция/страница "Сотрудники" (в блоке настроек начислений, по аналогии с `PayrollDocIdFormatSection`): список + та же модалка добавления.
- Поиск по документам (`employeeSearch` / `employee_search`) остаётся текстовым фильтром, но на бэкенде теперь матчится через `employee__full_name__icontains` — это фильтр для поиска, а не ввод данных, строгий выбор из справочника ему не нужен.

## Часть 2: Выплата по кассе

### Модель `payroll.PayrollPayout`

```python
class PayrollPayout(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="payroll_payouts")
    line = models.ForeignKey(PayrollLine, on_delete=models.PROTECT, related_name="payouts")
    cash_expense = models.OneToOneField(
        "cashier.CashExpense", on_delete=models.PROTECT, related_name="payroll_payout"
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_payouts"
```

Живёт в модуле `payroll` — не требует изменений ни в `requests`, ни в `cashier` (кроме нового `related_name` на `CashExpense`, которое не влияет на существующую логику этой модели).

### Сервис `create_payroll_line_payout` (`payroll/services.py`)

Новая функция, ничего существующего не модифицирует:

```python
def create_payroll_line_payout(*, line: PayrollLine, amount: Decimal, actor_user) -> PayrollPayout:
```

Шаги:

1. **Заявка согласована.** Через `line.document` найти связанную `Request` (`expense_ref_target=PAYROLL, expense_ref_id=line.document_id`). Если её нет или `status != PAYED` — `ValidationError`: выплата возможна только после полного согласования заявки на весь документ.
2. **Модуль кассы включён.** Тот же паттерн `_is_module_enabled(tenant=..., module_key="cash")`, что уже используется в `requests/services.py::create_expense_for_request_payment` — если выключен, `ValidationError`.
3. **Блокировка от перевыплаты.** Под `select_for_update()` на строке (или на агрегате её выплат) посчитать `paid_so_far = line.payouts.aggregate(Sum("cash_expense__amount"))`. Если `paid_so_far + amount > line.sum` — жёсткий отказ (`ValidationError` с текущим остатком в сообщении).
4. **Создание `CashExpense`.** Кошелёк — через уже существующий `assign_wallet_for_cash_movement`. `external_id=f"payroll-payout-{line.id}-{uuid4().hex[:8]}"` (или порядковый номер), `title=f"ЗП: {line.employee.full_name}"`, `amount=amount`, `payload={"payroll_line_id": line.id, "source": "payroll_payout"}`.
5. **Создание `PayrollPayout`**, связывающего строку и `CashExpense`.

Всё под одной транзакцией.

Выплата не обязана закрывать всю сумму строки: `amount` может быть меньше остатка (`line.sum - paid_so_far`) — недоплата допустима и это нормальный сценарий (довыплатить остаток можно позже отдельной операцией). Блокируется только превышение остатка.

### API

- `POST /api/payroll/lines/{id}/payouts/` — `{"amount": "..."}` → `create_payroll_line_payout`. Права — доступ к модулю `payroll` (`HasEffectiveModuleAccess`); проверка модуля `cash` — внутри сервиса.
- `POST /api/payroll/lines/payouts/bulk/` — групповая выплата: `{"payouts": [{"line_id": 1, "amount": "..."}, {"line_id": 2, "amount": "..."}]}`. Кассир выбирает несколько строк разом (каждая — свой сотрудник) и проводит одним действием. Под капотом — та же `create_payroll_line_payout` на каждую пару `(line_id, amount)`, в одной транзакции: либо все проходят, либо (если хоть одна не прошла валидацию — не `PAYED`, превышение остатка, модуль кассы выключен) откатываются все, с построчным списком ошибок в ответе. Каждая строка по-прежнему получает свой отдельный `CashExpense` и `PayrollPayout` (как зафиксировано выше — не объединяем несколько сотрудников в одну кассовую запись), групповое действие — это только UI/API-удобство, не отдельная сущность в БД.
- Детальный сериализатор строки (`PayrollLineSerializer`) дополняется read-only полями: `paid_amount`, `remaining_amount`, `payouts: [{id, amount, created_at, created_by}]`.

### Фронтенд

В детальном виде начисления, для каждой строки, если связанная заявка в статусе `PAYED`: показывается "Выплачено X из Y" и чекбокс для выбора строки + поле суммы (по умолчанию — остаток, редактируемо). Кнопка "Выплатить" доступна как на одной строке (сразу), так и над таблицей — "Выплатить выбранным" для нескольких отмеченных строк разом (вызывает bulk-эндпоинт). Там же — история выплат по строке (дата, сумма, кто провёл).

## Тестирование

Обе части покрываются через `Backend Tests` (GitHub Actions) после пуша — локальный прогон запрещён правилами проекта.

- Создание/поиск сотрудника, уникальность `(tenant, full_name)`.
- n8n-импорт: авто-резолв существующего сотрудника по точному имени; авто-создание нового, если не найден.
- Портал: нельзя сохранить строку начисления без `employee`.
- Бэкафилл-миграция (данные без потерь: все исторические строки получают `employee_fk`, соответствующий их прежнему тексту).
- Выплата: блокировка до `PAYED`; блокировка при выключенном модуле кассы; блокировка перевыплаты (сумма > остатка строки); частичная выплата (меньше остатка) проходит и корректно накапливается несколькими операциями; успешный кейс создаёт `CashExpense` с правильной суммой/кошельком и корректно обновляет `paid_amount`/`remaining_amount`; конкурентная гонка двух выплат (через `select_for_update`) не даёт превысить сумму строки.
- Групповая выплата: успешный кейс создаёт по одному `CashExpense`/`PayrollPayout` на каждую строку из списка; если хоть одна строка в списке не проходит валидацию — откатывается вся операция (ни один `CashExpense` не создаётся), ответ содержит построчные ошибки.

## Затронутые файлы (ориентировочно)

- `backend_v2/apps/modules/payroll/models.py` — `Employee`, `PayrollPayout`, смена типа `PayrollLine.employee`.
- `backend_v2/apps/modules/payroll/migrations/` — 3 миграции (фазы A/B/C).
- `backend_v2/apps/modules/payroll/services.py` — `create_payroll_line_payout`; правка `create_payroll_document` под FK.
- `backend_v2/apps/modules/payroll/serializers.py`, `views.py`, `urls.py` — эндпоинты сотрудников и выплат, поля `paid_amount`/`remaining_amount`.
- `backend_v2/apps/modules/n8n_integration/serializers.py` — `N8nPayrollLineImportSerializer` резолвит/создаёт `Employee` по имени.
- `frontend_v2/src/lib/api.ts` — `listEmployees`, `createEmployee`, `createPayrollPayout`.
- `frontend_v2/src/ui/PayrollPage.tsx` — `Select` вместо `Input` для сотрудника, секция "Сотрудники", UI выплаты по строке.
- Новый `frontend_v2/src/ui/EmployeeCreateModal.tsx`.
