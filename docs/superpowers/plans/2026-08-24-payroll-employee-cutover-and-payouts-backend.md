# Справочник сотрудников — cutover + Выплаты по кассе (бэкенд) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the employee-directory rollout (Phase C: make `PayrollLine.employee` an FK, remove the old text field) and build the cash-payout backend (`PayrollPayout` model, service, API) on top of it — so a cashier can record an actual cash disbursement against an already-approved payroll accrual line.

**Architecture:** Three schema migrations finish the Phase A/B→C cutover (drop the old text column, rename `employee_fk`→`employee`, enforce `NOT NULL`); `N8nPayrollLineImportSerializer` and `PayrollLineCreateSerializer` switch to resolving/requiring an `Employee` instead of free text; a new `Employee` list/create API backs the directory. A new `PayrollPayout` model (in `payroll`, referencing `cashier.CashExpense`) and `payroll/services.py` functions (`create_payroll_line_payout`, `create_payroll_line_payouts_bulk`) implement the payout rule: only after the linked `Request` is `PAYED`, never exceeding the line's remaining amount. Frontend gets a `Select`-based employee picker with inline quick-add in the accrual-creation form, and an employee-directory section added to the settings page from the previous plan.

**Tech Stack:** Django, Django REST Framework, React + TypeScript, Ant Design.

**Spec:** `docs/superpowers/specs/2026-08-24-payroll-cash-payouts-design.md` (Часть 1 "Фаза C" onward, Часть 2 in full)

**Prerequisite:** `docs/superpowers/plans/2026-08-24-payroll-employee-directory-schema-backfill.md` must be merged, deployed, and its "Post-Merge Manual Verification" section confirmed (zero `PayrollLine` rows with `employee_fk_id IS NULL AND employee != ''`) before starting Task 1 of this plan. Also requires `docs/superpowers/plans/2026-08-24-payroll-settings-relocation.md` merged first (Task 6 here extends the `PayrollSettingsPage.tsx` file it creates).

## Global Constraints

- Migrations only via `make makemigrations` (never local `python manage.py makemigrations`).
- No data deletion beyond the already-verified-redundant old `employee` text column (its content is fully preserved in `Employee.full_name` / `employee_fk` per the prerequisite plan).
- `select_for_update()` guards every payout write against overpaying past a line's remaining amount.
- No local test runs — verify via GitHub Actions "Backend Tests" after push.
- Payroll module code must not modify shared `requests`/`cashier` module internals — only add new code in `payroll` that reuses their public models/helpers (OCP).

---

### Task 1: Cutover migrations — finish `PayrollLine.employee` as a mandatory FK

**Files:**
- Modify: `backend_v2/apps/modules/payroll/models.py`
- Create (generated): three migration files under `backend_v2/apps/modules/payroll/migrations/`

**Interfaces:**
- Produces: `PayrollLine.employee` — now `ForeignKey(Employee, on_delete=models.PROTECT, related_name="payroll_lines")`, mandatory (`null=False`). Consumed by every task below and by the frontend.

- [ ] **Step 1: Drop the old text column**

In `backend_v2/apps/modules/payroll/models.py`, remove the old `employee = models.TextField()` line from `PayrollLine` entirely, leaving only `employee_fk` (still nullable, still named `employee_fk`) unchanged for now.

Run: `make makemigrations`

Confirm (via `ls backend_v2/apps/modules/payroll/migrations/ | sort` and reading the new file) it contains exactly one `RemoveField` operation for `employee` on `PayrollLine`.

- [ ] **Step 2: Rename `employee_fk` to `employee`**

In `models.py`, rename the field `employee_fk` to `employee` (keep it nullable for this step — do not add `null=False` yet):

```python
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_lines",
    )
```

Run: `make makemigrations`

Confirm the generated migration is a single `RenameField` operation (`employee_fk` → `employee`) on `PayrollLine`, **not** a `RemoveField`+`AddField` pair. If `make makemigrations` prompts or generates a remove/add pair instead of a rename, stop and re-check that Step 1's migration was applied cleanly first and that no other field changed in this diff — a rename is only auto-detected when exactly one field changes name with everything else identical.

- [ ] **Step 3: Enforce `NOT NULL`**

In `models.py`, set `null=False, blank=False` on the now-renamed `employee` field:

```python
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="payroll_lines",
    )
```

Run: `make makemigrations`

Confirm the generated migration is a single `AlterField` operation setting `employee` to non-nullable. This is safe only because the prerequisite plan's manual verification already confirmed every row has a non-null value.

- [ ] **Step 4: Update model tests for the new shape**

In `backend_v2/apps/modules/payroll/tests.py`, every `PayrollLine.objects.create(...)` call currently passes `employee="Some Name"` (a string). Update every such call across the file to pass `employee=<an Employee instance>` instead — create the `Employee` first. For example, in `PayrollSmokeTests.test_can_create_document_and_line`:

```python
class PayrollSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

    def test_can_create_document_and_line(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id="DOC-1")
        employee = Employee.objects.create(tenant=self.tenant, full_name="John")
        line = PayrollLine.objects.create(
            document=doc,
            line_no=1,
            employee=employee,
            item="Salary",
            description="",
            sum="100.00",
            days_plan=20,
            days_fact=20,
            period_start=timezone.now().date(),
            period_end=timezone.now().date(),
            approval=False,
        )
        self.assertIsNotNone(doc.id)
        self.assertIsNotNone(line.id)
        self.assertEqual(PayrollDocument.objects.filter(tenant=self.tenant).count(), 1)
        self.assertEqual(doc.lines.count(), 1)
```

Apply the same transformation (create an `Employee` per distinct name used, pass the instance instead of the string) to: `PayrollApiTests.setUp` (two lines, "Alice Smith" and "Bob Jones"), `PayrollNativeDocumentModelTests.test_line_optional_fields_can_be_null` ("Jane"), `MaybeCreateLinkedRequestTests.setUp` ("Alice", "Bob"), and `EmployeeModelTests.test_payroll_line_employee_fk_is_optional_and_links_to_employee` from the prerequisite plan — that test specifically exercised the old "line without fk" case, which is no longer possible; **delete** that test entirely (it tested transitional Phase A/B behavior that no longer applies) and replace it with:

```python
    def test_payroll_line_requires_employee(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        emp = Employee.objects.create(tenant=self.tenant, full_name="Bob Jones")
        line = PayrollLine.objects.create(
            document=doc, line_no=1, employee=emp, item="Salary",
            description="", sum="200.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=False,
        )
        self.assertEqual(line.employee_id, emp.id)
        self.assertEqual(emp.payroll_lines.count(), 1)
```

Also fix `PayrollApiTests.test_detail_returns_document_with_lines` and `test_list_filtered_by_employee_search`, which currently assert on `res.data["lines"][i]["employee"]` / query params against a plain string — these will be addressed in Task 3 (they depend on the serializer shape change), so leave their assertions as-is in this task; Task 3 updates them.

- [ ] **Step 5: Push and verify via CI**

Push (`make push`), confirm "Backend Tests" passes.

- [ ] **Step 6: Commit**

```bash
git add backend_v2/apps/modules/payroll/models.py backend_v2/apps/modules/payroll/migrations/ backend_v2/apps/modules/payroll/tests.py
git commit -m "feat(payroll): cut over PayrollLine.employee to a mandatory Employee FK"
```

---

### Task 2: n8n import resolves/creates `Employee` by name

**Files:**
- Modify: `backend_v2/apps/modules/n8n_integration/serializers.py:167-211` (`N8nPayrollLineImportSerializer`)
- Test: `backend_v2/apps/modules/n8n_integration/tests.py` (or the module's existing test file for payroll n8n import — locate via `grep -rln "N8nPayrollLineImportSerializer\|payroll-lines" backend_v2/apps/modules/n8n_integration/tests*.py`)

**Interfaces:**
- Consumes: `payroll.models.Employee` (Task 1 / prerequisite plan).
- Produces: n8n's external JSON contract for `employee` stays a string; server resolves it to an `Employee` transparently.

- [ ] **Step 1: Locate existing n8n payroll-line tests**

Run: `grep -rn "N8nPayrollLineImportSerializer\|payroll-lines\|payroll/lines" backend_v2/apps/modules/n8n_integration/tests.py`

Note the test class name and existing assertions on `employee` so Step 3 extends the same file consistently.

- [ ] **Step 2: Update the serializer**

In `backend_v2/apps/modules/n8n_integration/serializers.py`, add the import at the top:

```python
from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine
```

Replace the `N8nPayrollLineImportSerializer` class body (currently lines 167-211) with:

```python
class N8nPayrollLineImportSerializer(serializers.ModelSerializer):
    """Upsert payroll line by id; doc_id ties to PayrollDocument (auto-created).
    `employee` stays a plain name string on the wire — resolved to/created in the
    Employee directory server-side so n8n's contract never has to change."""

    id = serializers.IntegerField(required=False)
    doc_id = serializers.CharField(write_only=True)
    employee = serializers.CharField(write_only=True)

    class Meta:
        model = PayrollLine
        fields = [
            "id",
            "doc_id",
            "line_no",
            "employee",
            "item",
            "description",
            "sum",
            "days_plan",
            "days_fact",
            "period_start",
            "period_end",
            "approval",
        ]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["doc_id"] = instance.document.doc_id
        ret["employee"] = instance.employee.full_name
        return ret

    def _resolve_employee(self, tenant, validated_data):
        name = validated_data.pop("employee", None)
        if name is None:
            return
        name = name.strip()
        employee, _ = Employee.objects.get_or_create(tenant=tenant, full_name=name)
        validated_data["employee"] = employee

    def create(self, validated_data):
        line_id = validated_data.pop("id", None)
        doc_id = validated_data.pop("doc_id")
        tenant = self.context["request"].tenant
        doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
        self._resolve_employee(tenant, validated_data)
        if line_id is None:
            return PayrollLine.objects.create(document=doc, **validated_data)
        return PayrollLine.objects.create(id=line_id, document=doc, **validated_data)

    def update(self, instance, validated_data):
        doc_id = validated_data.pop("doc_id", None)
        tenant = self.context["request"].tenant
        if doc_id is not None:
            doc, _ = PayrollDocument.objects.get_or_create(tenant=tenant, doc_id=doc_id)
            validated_data["document"] = doc
        self._resolve_employee(tenant, validated_data)
        validated_data.pop("id", None)
        return super().update(instance, validated_data)
```

- [ ] **Step 3: Write tests**

Append to the test file located in Step 1 (adjust the exact endpoint path/host setup to match that file's existing conventions for payroll-line n8n tests — reuse its existing `setUp`/auth/tenant fixtures rather than duplicating them):

```python
def test_import_creates_employee_when_not_found(self):
    payload = {
        "doc_id": "N8N-DOC-1",
        "line_no": 1,
        "employee": "Newly Imported Person",
        "item": "Salary",
        "sum": "500.00",
    }
    res = self.client.post(self.payroll_lines_url, payload, format="json", HTTP_HOST=self.host)
    self.assertEqual(res.status_code, 201, res.content)
    self.assertEqual(res.data["employee"], "Newly Imported Person")
    self.assertEqual(Employee.objects.filter(tenant=self.tenant, full_name="Newly Imported Person").count(), 1)

def test_import_reuses_existing_employee_by_exact_name(self):
    Employee.objects.create(tenant=self.tenant, full_name="Existing Person")
    payload = {
        "doc_id": "N8N-DOC-2",
        "line_no": 1,
        "employee": "Existing Person",
        "item": "Salary",
        "sum": "500.00",
    }
    res = self.client.post(self.payroll_lines_url, payload, format="json", HTTP_HOST=self.host)
    self.assertEqual(res.status_code, 201, res.content)
    self.assertEqual(Employee.objects.filter(tenant=self.tenant, full_name="Existing Person").count(), 1)
```

Add `from apps.modules.payroll.models import Employee` to that test file's imports if not already present. Adjust `self.payroll_lines_url`/`self.host`/`self.client` to whatever attribute names Step 1's existing test class already uses (do not invent new fixture attribute names — match the file's existing convention exactly).

- [ ] **Step 4: Push and verify via CI**

Push, confirm "Backend Tests" passes.

- [ ] **Step 5: Commit**

```bash
git add backend_v2/apps/modules/n8n_integration/serializers.py backend_v2/apps/modules/n8n_integration/tests.py
git commit -m "feat(n8n): resolve/create Employee by name on payroll-line import"
```

---

### Task 3: Portal create/read serializers switch to `Employee`

**Files:**
- Modify: `backend_v2/apps/modules/payroll/serializers.py`
- Test: `backend_v2/apps/modules/payroll/tests.py`

**Interfaces:**
- Consumes: `Employee` (Task 1).
- Produces: `PayrollLineCreateSerializer.employee` — now a tenant-scoped `PrimaryKeyRelatedField`. `PayrollLineSerializer.employee` — now `{"id": int, "full_name": str}` instead of a plain string, plus new `paid_amount`/`remaining_amount`/`payouts` fields (populated in Task 8, `0` / `[]` for now since `PayrollPayout` doesn't exist until Task 7 — write these methods now against `line.payouts` so Task 7/8 need no further serializer changes; they will simply start returning non-empty once `PayrollPayout` exists).

- [ ] **Step 1: Rewrite `backend_v2/apps/modules/payroll/serializers.py`**

Replace the full file content with:

```python
from decimal import Decimal

from django.db.models import Sum
from rest_framework import serializers

from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine


class PayrollLineSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    employee = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    payouts = serializers.SerializerMethodField()

    class Meta:
        model = PayrollLine
        fields = [
            "id",
            "line_no",
            "employee",
            "item",
            "description",
            "sum",
            "days_plan",
            "days_fact",
            "period_start",
            "period_end",
            "approval",
            "paid_amount",
            "remaining_amount",
            "payouts",
        ]
        read_only_fields = fields

    def get_employee(self, obj):
        return {"id": obj.employee_id, "full_name": obj.employee.full_name}

    def get_paid_amount(self, obj):
        agg = obj.payouts.aggregate(s=Sum("cash_expense__amount"))
        return agg.get("s") or Decimal("0")

    def get_remaining_amount(self, obj):
        return obj.sum - self.get_paid_amount(obj)

    def get_payouts(self, obj):
        return [
            {
                "id": p.id,
                "amount": p.cash_expense.amount,
                "created_at": p.created_at,
                "created_by_full_name": (
                    (getattr(p.created_by, "full_name", "") or "").strip() or getattr(p.created_by, "username", "")
                ),
            }
            for p in obj.payouts.select_related("cash_expense", "created_by").order_by("-created_at")
        ]


class PayrollDocumentListSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    total_sum = serializers.DecimalField(max_digits=18, decimal_places=2, read_only=True, default=Decimal("0"))
    paid_amount = serializers.SerializerMethodField()
    lines_count = serializers.IntegerField(read_only=True, default=0)
    has_request = serializers.BooleanField(read_only=True)
    has_paid_request = serializers.BooleanField(read_only=True)
    matched_request_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = PayrollDocument
        fields = [
            "id",
            "doc_id",
            "created_at",
            "total_sum",
            "paid_amount",
            "lines_count",
            "has_request",
            "has_paid_request",
            "matched_request_id",
        ]
        read_only_fields = fields

    def get_paid_amount(self, obj):
        from apps.modules.payroll.models import PayrollPayout

        agg = PayrollPayout.objects.filter(line__document=obj).aggregate(s=Sum("cash_expense__amount"))
        return agg.get("s") or Decimal("0")


class PayrollDocumentDetailSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    lines = PayrollLineSerializer(many=True, read_only=True)
    total_sum = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    request_status = serializers.SerializerMethodField()

    class Meta:
        model = PayrollDocument
        fields = ["id", "doc_id", "created_at", "total_sum", "paid_amount", "request_status", "lines"]
        read_only_fields = fields

    def get_total_sum(self, obj):
        agg = obj.lines.aggregate(s=Sum("sum"))
        val = agg.get("s")
        return val if val is not None else Decimal("0")

    def get_paid_amount(self, obj):
        from apps.modules.payroll.models import PayrollPayout

        agg = PayrollPayout.objects.filter(line__document=obj).aggregate(s=Sum("cash_expense__amount"))
        val = agg.get("s")
        return val if val is not None else Decimal("0")

    def get_request_status(self, obj):
        from apps.modules.requests.models import Request

        return (
            Request.objects.filter(
                tenant_id=obj.tenant_id,
                expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
                expense_ref_id=obj.id,
            )
            .values_list("status", flat=True)
            .first()
        )


class PayrollLineCreateSerializer(serializers.Serializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    item = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True, default="")
    sum = serializers.DecimalField(max_digits=15, decimal_places=2)
    days_plan = serializers.IntegerField(required=False, allow_null=True, default=None)
    days_fact = serializers.IntegerField(required=False, allow_null=True, default=None)
    period_start = serializers.DateField(required=False, allow_null=True, default=None)
    period_end = serializers.DateField(required=False, allow_null=True, default=None)

    def validate_employee(self, value):
        tenant = getattr(self.context.get("request"), "tenant", None)
        if tenant is None or value.tenant_id != tenant.id:
            raise serializers.ValidationError("Сотрудник не найден.")
        return value


class PayrollDocumentCreateSerializer(serializers.Serializer):
    lines = PayrollLineCreateSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Нужна хотя бы одна строка начисления.")
        return value
```

`PayrollPayout` is imported lazily inside the two `get_paid_amount` methods (not at module top level) because it doesn't exist yet until Task 7 of this same plan — this avoids an import-order problem while writing Task 3 first. Once Task 7 lands, these lazy imports keep working unchanged (no need to revisit this file).

Note `PrimaryKeyRelatedField.validate_employee` — validating tenant ownership in `validate_employee` (rather than restricting the field's `queryset` at class-definition time) is required here because `PayrollLineCreateSerializer` is nested inside `PayrollDocumentCreateSerializer` via `many=True`; DRF only binds nested-serializer `context` (and therefore `self.context["request"].tenant`) once validation runs, not at `__init__` time, so filtering the queryset in `__init__` would silently see no request/tenant.

`create_payroll_document` in `backend_v2/apps/modules/payroll/services.py` needs **no changes** — its existing line `employee=line_data["employee"]` already receives an `Employee` instance (not a string) because `PrimaryKeyRelatedField.to_internal_value` resolves the posted id to the model instance before `validated_data` is built, and `PayrollLine.objects.create(employee=<instance>, ...)` works unchanged with the new FK field. Confirm this by reading `backend_v2/apps/modules/payroll/services.py:26-49` — no edit needed there.

- [ ] **Step 2: Update existing tests for the new serializer shapes**

In `backend_v2/apps/modules/payroll/tests.py`:

1. `PayrollApiTests.setUp` — after creating `self.doc`, create two employees and pass them by FK (already done in Task 1 Step 4); now also update:
2. `test_detail_returns_document_with_lines` — `employee` is now a dict, not a string:
   ```python
   def test_detail_returns_document_with_lines(self):
       self.client.force_authenticate(self.user)
       res = self.client.get(f"/api/payroll/documents/{self.doc.pk}/", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 200)
       self.assertEqual(res.data["doc_id"], "PAY-2024-01")
       self.assertIn("lines", res.data)
       self.assertEqual(len(res.data["lines"]), 2)
       employee_names = {line["employee"]["full_name"] for line in res.data["lines"]}
       self.assertIn("Alice Smith", employee_names)
       self.assertIn("Bob Jones", employee_names)
       for line in res.data["lines"]:
           self.assertEqual(Decimal(str(line["paid_amount"])), Decimal("0"))
           self.assertEqual(Decimal(str(line["remaining_amount"])), Decimal(str(line["sum"])))
   ```
3. `test_list_filtered_by_employee_search` — the query param stays a plain string (it filters `employee__full_name__icontains`, matching Task 4 below), so this test's request stays `?employee_search=Alice`; no change needed to the test itself, only confirm it still passes once `PayrollDocumentViewSet.get_queryset` (Task 4, Step 3) switches the filter to `employee__full_name__icontains`.
4. `PayrollDocumentCreateApiTests` — every payload currently sends `"employee": "Alice Smith"` (a name string). Update `setUp` to create `Employee` rows and change every payload to send `"employee": <employee.id>`:
   ```python
   def setUp(self):
       self.tenant = Tenant.objects.create(name="CreateAcme", subdomain="create-acme", is_active=True)
       self.user = User.objects.create_user(username="create-accountant", password="x")
       self.outsider = User.objects.create_user(username="no-access-user", password="x")
       TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
       TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ACCOUNTANT)
       TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
       self.host = "create-acme.example.com"
       self.url = "/api/payroll/documents/create/"
       self.alice = Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
       self.bob = Employee.objects.create(tenant=self.tenant, full_name="Bob Jones")

   def test_creates_document_with_lines_and_no_doc_id(self):
       self.client.force_authenticate(self.user)
       payload = {
           "lines": [
               {"employee": self.alice.id, "item": "Salary", "sum": "1500.00"},
               {"employee": self.bob.id, "item": "Bonus", "sum": "500.00", "days_plan": 22, "days_fact": 20},
           ]
       }
       res = self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 201, res.content)
       self.assertIsNone(res.data["doc_id"])
       self.assertEqual(len(res.data["lines"]), 2)
       doc = PayrollDocument.objects.get(pk=res.data["id"])
       self.assertEqual(doc.tenant_id, self.tenant.id)
       self.assertEqual(doc.created_by_id, self.user.id)
       self.assertEqual(list(doc.lines.order_by("line_no").values_list("line_no", flat=True)), [1, 2])

   def test_requires_at_least_one_line(self):
       self.client.force_authenticate(self.user)
       res = self.client.post(self.url, {"lines": []}, format="json", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 400)

   def test_unauthenticated_returns_401(self):
       res = self.client.post(self.url, {"lines": []}, format="json", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 401)

   def test_user_without_payroll_module_access_forbidden(self):
       TenantMembership.objects.create(tenant=self.tenant, user=self.outsider, is_active=True)
       TenantUserRole.objects.create(tenant=self.tenant, user=self.outsider, role=TenantUserRole.ROLE_REQUESTER)
       self.client.force_authenticate(self.outsider)
       payload = {"lines": [{"employee": self.alice.id, "item": "Salary", "sum": "100.00"}]}
       res = self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 403)

   def test_existing_readonly_list_endpoint_unaffected(self):
       self.client.force_authenticate(self.user)
       payload = {"lines": [{"employee": self.alice.id, "item": "Salary", "sum": "100.00"}]}
       self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
       res = self.client.get("/api/payroll/documents/", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 200)

   def test_employee_from_another_tenant_is_rejected(self):
       other_tenant = Tenant.objects.create(name="OtherEmpTenant", subdomain="other-emp-tenant", is_active=True)
       foreign_employee = Employee.objects.create(tenant=other_tenant, full_name="Foreign Person")
       self.client.force_authenticate(self.user)
       payload = {"lines": [{"employee": foreign_employee.id, "item": "Salary", "sum": "100.00"}]}
       res = self.client.post(self.url, payload, format="json", HTTP_HOST=self.host)
       self.assertEqual(res.status_code, 400)
   ```
   Add `from decimal import Decimal` at the top of `tests.py` if not already imported (it already is, per the file's first line).

- [ ] **Step 3: Push and verify via CI**

Push, confirm "Backend Tests" passes.

- [ ] **Step 4: Commit**

```bash
git add backend_v2/apps/modules/payroll/serializers.py backend_v2/apps/modules/payroll/tests.py
git commit -m "feat(payroll): switch line create/read serializers to the Employee FK"
```

---

### Task 4: Employee directory list/create API

**Files:**
- Modify: `backend_v2/apps/modules/payroll/views.py`
- Modify: `backend_v2/apps/modules/payroll/urls.py`
- Modify: `backend_v2/apps/modules/payroll/serializers.py` (append `EmployeeSerializer`, `EmployeeCreateSerializer`)
- Test: `backend_v2/apps/modules/payroll/tests.py`

**Interfaces:**
- Produces: `GET /api/payroll/employees/` (paginated, `?search=` filter), `POST /api/payroll/employees/create/` (`{"full_name": "..."}` → 201 with `{"id", "full_name"}`). Consumed by the frontend (Task 5/6).

- [ ] **Step 1: Add the two serializers**

Append to `backend_v2/apps/modules/payroll/serializers.py`:

```python
class EmployeeSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Employee
        fields = ["id", "full_name"]
        read_only_fields = fields


class EmployeeCreateSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=200, trim_whitespace=True)

    def validate_full_name(self, value):
        v = value.strip()
        if not v:
            raise serializers.ValidationError("ФИО обязательно.")
        return v
```

- [ ] **Step 2: Add the views**

In `backend_v2/apps/modules/payroll/views.py`, add the import `Employee` to the existing `from apps.modules.payroll.models import PayrollDocument, PayrollLine` line (making it `from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine`), add `EmployeeSerializer, EmployeeCreateSerializer` to the existing serializers import, and append:

```python
class EmployeeCursorPagination(PortalCursorPagination):
    ordering = "full_name,id"


class EmployeeViewSet(PortalListViewSetMixin, viewsets.ReadOnlyModelViewSet):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    lookup_field = "pk"
    pagination_class = EmployeeCursorPagination
    serializer_class = EmployeeSerializer
    ordering_fields = ["full_name", "id"]
    ordering = ["full_name", "id"]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return Employee.objects.none()
        qs = Employee.objects.filter(tenant=tenant).order_by("full_name", "id")
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(full_name__icontains=search)
        return qs


class EmployeeCreateView(generics.CreateAPIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = EmployeeCreateSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        employee, _ = Employee.objects.get_or_create(
            tenant=tenant,
            full_name=serializer.validated_data["full_name"],
            defaults={"created_by": request.user},
        )
        out = EmployeeSerializer(employee)
        return Response(out.data, status=status.HTTP_201_CREATED)
```

(`get_or_create` deliberately makes duplicate submissions idempotent instead of erroring — same resolution behavior as the n8n import path in Task 2, so a user quick-adding an employee that already exists from two browser tabs doesn't see a confusing uniqueness error.)

Also update `PayrollDocumentViewSet.get_queryset` (Step 3 below) for the `employee_search` filter to match the new FK.

- [ ] **Step 3: Update the `employee_search` filter for the FK**

In `backend_v2/apps/modules/payroll/views.py`, in `PayrollDocumentViewSet.get_queryset`, change:

```python
        employee_search = (self.request.query_params.get("employee_search") or "").strip()
        if employee_search:
            qs = qs.filter(
                Exists(
                    PayrollLine.objects.filter(
                        document_id=OuterRef("pk"),
                        employee__icontains=employee_search,
                    )
                )
            )
```

to:

```python
        employee_search = (self.request.query_params.get("employee_search") or "").strip()
        if employee_search:
            qs = qs.filter(
                Exists(
                    PayrollLine.objects.filter(
                        document_id=OuterRef("pk"),
                        employee__full_name__icontains=employee_search,
                    )
                )
            )
```

- [ ] **Step 4: Wire up URLs**

Replace `backend_v2/apps/modules/payroll/urls.py` with:

```python
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.payroll.views import (
    EmployeeCreateView,
    EmployeeViewSet,
    PayrollDocumentCreateView,
    PayrollDocumentViewSet,
)

router = DefaultRouter()
router.register(r"documents", PayrollDocumentViewSet, basename="payroll-documents")
router.register(r"employees", EmployeeViewSet, basename="payroll-employees")

urlpatterns = [
    path("documents/create/", PayrollDocumentCreateView.as_view(), name="payroll-documents-create"),
    path("employees/create/", EmployeeCreateView.as_view(), name="payroll-employees-create"),
    path("", include(router.urls)),
]
```

(`employees/create/` is registered before `include(router.urls)` for the same reason `documents/create/` already is — an exact-path match must be tried before the router's `employees/<pk>/` pattern, which would otherwise treat `create` as a primary key.)

- [ ] **Step 5: Write tests**

Append to `backend_v2/apps/modules/payroll/tests.py`:

```python
@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class EmployeeApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="EmpApiAcme", subdomain="emp-api-acme", is_active=True)
        self.user = User.objects.create_user(username="emp-api-accountant", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        self.host = "emp-api-acme.example.com"

    def test_create_employee(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/payroll/employees/create/", {"full_name": "Alice Smith"}, format="json", HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["full_name"], "Alice Smith")
        self.assertEqual(Employee.objects.filter(tenant=self.tenant, full_name="Alice Smith").count(), 1)

    def test_create_employee_is_idempotent_on_duplicate_name(self):
        self.client.force_authenticate(self.user)
        self.client.post("/api/payroll/employees/create/", {"full_name": "Alice Smith"}, format="json", HTTP_HOST=self.host)
        res = self.client.post("/api/payroll/employees/create/", {"full_name": "Alice Smith"}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Employee.objects.filter(tenant=self.tenant, full_name="Alice Smith").count(), 1)

    def test_create_employee_requires_full_name(self):
        self.client.force_authenticate(self.user)
        res = self.client.post("/api/payroll/employees/create/", {"full_name": "  "}, format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

    def test_list_employees_scoped_to_tenant(self):
        Employee.objects.create(tenant=self.tenant, full_name="In Tenant")
        other_tenant = Tenant.objects.create(name="EmpApiOther", subdomain="emp-api-other", is_active=True)
        Employee.objects.create(tenant=other_tenant, full_name="Other Tenant Person")
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/payroll/employees/", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        names = [e["full_name"] for e in list_results(res)]
        self.assertIn("In Tenant", names)
        self.assertNotIn("Other Tenant Person", names)

    def test_list_employees_filtered_by_search(self):
        Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        Employee.objects.create(tenant=self.tenant, full_name="Bob Jones")
        self.client.force_authenticate(self.user)
        res = self.client.get("/api/payroll/employees/?search=Alice", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        names = [e["full_name"] for e in list_results(res)]
        self.assertEqual(names, ["Alice Smith"])
```

- [ ] **Step 6: Push and verify via CI**

Push, confirm "Backend Tests" passes.

- [ ] **Step 7: Commit**

```bash
git add backend_v2/apps/modules/payroll/serializers.py backend_v2/apps/modules/payroll/views.py backend_v2/apps/modules/payroll/urls.py backend_v2/apps/modules/payroll/tests.py
git commit -m "feat(payroll): add Employee directory list/create API"
```

---

### Task 5: Frontend — employee `Select` + inline quick-add in the accrual form

**Files:**
- Create: `frontend_v2/src/ui/EmployeeCreateModal.tsx`
- Modify: `frontend_v2/src/lib/api.ts` (add `EmployeeDto`, `listEmployees`, `createEmployee`; change `PayrollLineCreatePayload.employee` type)
- Modify: `frontend_v2/src/ui/PayrollPage.tsx` (`CreatePayrollDocumentModal`)

**Interfaces:**
- Produces: `EmployeeDto = { id: number; full_name: string }`, `listEmployees(): Promise<EmployeeDto[]>`, `createEmployee(payload: { full_name: string }): Promise<EmployeeDto>` — all consumed by Task 6 too.

- [ ] **Step 1: Add API client functions**

In `frontend_v2/src/lib/api.ts`, add near the other payroll-related exports (after `createPayrollDocument`):

```ts
export type EmployeeDto = {
  id: number
  full_name: string
}

export async function listEmployees(search?: string): Promise<EmployeeDto[]> {
  const params = new URLSearchParams({ page_size: '200' })
  if (search && search.trim()) params.set('search', search.trim())
  const res = await apiFetch(`/api/payroll/employees/?${params.toString()}`)
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as { results?: EmployeeDto[] } | null
  return json?.results ?? []
}

export async function createEmployee(payload: { full_name: string }): Promise<EmployeeDto> {
  const res = await apiFetch('/api/payroll/employees/create/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await parseErrorBody(res))
  const json = (await res.json().catch(() => null)) as EmployeeDto | null
  if (!json) throw new Error('Пустой ответ от сервера')
  return json
}
```

Then change the existing `PayrollLineCreatePayload` type's `employee` field from `string` to `number`:

```ts
export type PayrollLineCreatePayload = {
  employee: number
  item: string
  description?: string
  sum: number
  days_plan?: number | null
  days_fact?: number | null
  period_start?: string | null
  period_end?: string | null
}
```

- [ ] **Step 2: Create the shared quick-add modal**

Create `frontend_v2/src/ui/EmployeeCreateModal.tsx`:

```tsx
import { useState } from 'react'
import { Form, Input, Modal, message } from 'antd'
import { createEmployee, type EmployeeDto } from '../lib/api'

export function EmployeeCreateModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (employee: EmployeeDto) => void
}) {
  const [form] = Form.useForm<{ full_name: string }>()
  const [saving, setSaving] = useState(false)

  const onSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const employee = await createEmployee({ full_name: values.full_name.trim() })
      message.success('Сотрудник добавлен')
      form.resetFields()
      onCreated(employee)
      onClose()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Добавить сотрудника"
      open={open}
      onCancel={onClose}
      onOk={() => void onSubmit()}
      confirmLoading={saving}
      okText="Добавить"
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item
          label="ФИО"
          name="full_name"
          rules={[{ required: true, message: 'ФИО обязательно' }]}
        >
          <Input placeholder="Иванов Иван Иванович" autoFocus />
        </Form.Item>
      </Form>
    </Modal>
  )
}
```

- [ ] **Step 3: Wire the `Select` + quick-add into `CreatePayrollDocumentModal`**

In `frontend_v2/src/ui/PayrollPage.tsx`:

1. Add imports: `Select` is already imported from `antd` (used elsewhere in the file); add `EmployeeCreateModal` and the new API functions:
   ```tsx
   import { EmployeeCreateModal } from './EmployeeCreateModal'
   ```
   and extend the existing `../lib/api` import to include `listEmployees`, `type EmployeeDto`.

2. Change `CreatePayrollLineFormValue.employee` from `string` to `number`:
   ```tsx
   type CreatePayrollLineFormValue = {
     employee: number
     item: string
     description?: string
     sum: number
     days_plan?: number | null
     days_fact?: number | null
     period?: [Dayjs, Dayjs] | null
   }
   ```

3. Rewrite `CreatePayrollDocumentModal` to load employees on open and use a `Select` for the employee field:

```tsx
function CreatePayrollDocumentModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: () => void
}) {
  const [form] = Form.useForm<{ lines: CreatePayrollLineFormValue[] }>()
  const [saving, setSaving] = useState(false)
  const [employees, setEmployees] = useState<EmployeeDto[]>([])
  const [employeesLoading, setEmployeesLoading] = useState(false)
  const [addEmployeeOpen, setAddEmployeeOpen] = useState(false)
  const [addEmployeeForField, setAddEmployeeForField] = useState<number | null>(null)

  const loadEmployees = async () => {
    setEmployeesLoading(true)
    try {
      setEmployees(await listEmployees())
    } catch {
      // Section degrades to an empty list; the user can still open the quick-add modal.
    } finally {
      setEmployeesLoading(false)
    }
  }

  useEffect(() => {
    if (open) void loadEmployees()
  }, [open])

  const onSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      const lines: PayrollLineCreatePayload[] = values.lines.map((line) => ({
        employee: line.employee,
        item: line.item,
        description: line.description,
        sum: line.sum,
        days_plan: line.days_plan ?? null,
        days_fact: line.days_fact ?? null,
        period_start: line.period?.[0]?.format('YYYY-MM-DD') ?? null,
        period_end: line.period?.[1]?.format('YYYY-MM-DD') ?? null,
      }))
      await createPayrollDocument({ lines })
      message.success('Начисление создано')
      form.resetFields()
      onCreated()
      onClose()
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'errorFields' in e) return
      message.error(e instanceof Error ? e.message : 'Ошибка создания')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="Создать начисление"
      open={open}
      onCancel={onClose}
      onOk={() => void onSubmit()}
      confirmLoading={saving}
      width={900}
      okText="Создать"
      destroyOnClose
    >
      <Form form={form} layout="vertical" initialValues={{ lines: [{}] }}>
        <Form.List name="lines">
          {(fields, { add, remove }) => (
            <Space direction="vertical" style={{ display: 'flex' }} size={12}>
              {fields.map((field) => (
                <Space key={field.key} align="baseline" wrap>
                  <Form.Item
                    {...field}
                    name={[field.name, 'employee']}
                    rules={[{ required: true, message: 'Сотрудник обязателен' }]}
                  >
                    <Select
                      showSearch
                      loading={employeesLoading}
                      placeholder="Сотрудник"
                      style={{ width: 220 }}
                      optionFilterProp="label"
                      options={employees.map((e) => ({ value: e.id, label: e.full_name }))}
                      popupRender={(menu) => (
                        <>
                          {menu}
                          <div style={{ padding: '4px 8px', borderTop: '1px solid #f0f0f0' }}>
                            <Button
                              type="link"
                              size="small"
                              icon={<PlusOutlined />}
                              onClick={() => {
                                setAddEmployeeForField(field.name)
                                setAddEmployeeOpen(true)
                              }}
                            >
                              Добавить сотрудника
                            </Button>
                          </div>
                        </>
                      )}
                    />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'item']}
                    rules={[{ required: true, message: 'Вид начисления обязателен' }]}
                  >
                    <Input placeholder="Вид (Salary / Bonus…)" style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'description']}>
                    <Input placeholder="Описание" style={{ width: 160 }} />
                  </Form.Item>
                  <Form.Item
                    {...field}
                    name={[field.name, 'sum']}
                    rules={[{ required: true, message: 'Сумма обязательна' }]}
                  >
                    <InputNumber placeholder="Сумма" min={0} style={{ width: 130 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'days_plan']}>
                    <InputNumber placeholder="Дни план" min={0} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'days_fact']}>
                    <InputNumber placeholder="Дни факт" min={0} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item {...field} name={[field.name, 'period']}>
                    <DatePicker.RangePicker placeholder={['Период от', 'Период до']} />
                  </Form.Item>
                  {fields.length > 1 ? (
                    <Button icon={<DeleteOutlined />} onClick={() => remove(field.name)} />
                  ) : null}
                </Space>
              ))}
              <Button type="dashed" icon={<PlusOutlined />} onClick={() => add()}>
                Добавить строку
              </Button>
            </Space>
          )}
        </Form.List>
      </Form>
      <EmployeeCreateModal
        open={addEmployeeOpen}
        onClose={() => setAddEmployeeOpen(false)}
        onCreated={(employee) => {
          setEmployees((prev) => [...prev, employee])
          if (addEmployeeForField !== null) {
            const current = form.getFieldValue('lines') as CreatePayrollLineFormValue[]
            current[addEmployeeForField] = { ...current[addEmployeeForField], employee: employee.id }
            form.setFieldsValue({ lines: current })
          }
        }}
      />
    </Modal>
  )
}
```

If this antd version does not support the `popupRender` prop on `Select` (it was renamed from `dropdownRender` in newer antd major versions), check the installed antd version with `cat frontend_v2/package.json | grep '"antd"'` and use `dropdownRender` instead if the installed version predates the rename — the prop signature (`(menu: ReactNode) => ReactNode`) is identical either way, only the prop name differs.

- [ ] **Step 4: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 5: Manual smoke check**

Using the `run` skill or local dev server: open "Создать начисление", confirm the employee field is a searchable dropdown, confirm "Добавить сотрудника" opens the quick-add modal, confirm creating a new employee there immediately selects it in the line that triggered it, and confirm submitting the form creates the document successfully end-to-end (hits the real backend from Task 3).

- [ ] **Step 6: Commit**

```bash
git add frontend_v2/src/ui/EmployeeCreateModal.tsx frontend_v2/src/lib/api.ts frontend_v2/src/ui/PayrollPage.tsx
git commit -m "feat(payroll): employee picker with inline quick-add in accrual creation form"
```

---

### Task 6: Frontend — employee directory section on the settings page

**Files:**
- Modify: `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx` (created by the settings-relocation plan)

**Interfaces:**
- Consumes: `listEmployees`, `EmployeeDto` (Task 5), `EmployeeCreateModal` (Task 5).

- [ ] **Step 1: Add an employee-list section**

In `frontend_v2/src/ui/settings/PayrollSettingsPage.tsx`, add the import:

```tsx
import { Button, Card, Checkbox, Form, Input, InputNumber, List, Typography, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { EmployeeCreateModal } from '../EmployeeCreateModal'
import {
  getTenantPayrollDocIdFormat,
  getTenantPayrollSettings,
  listEmployees,
  updateTenantPayrollDocIdFormat,
  updateTenantPayrollSettings,
  type EmployeeDto,
} from '../../lib/api'
```

(`List` and `PlusOutlined` are new; merge them into the existing import lines from Task 1 of the settings-relocation plan rather than duplicating the `antd`/`@ant-design/icons` import statements.)

Add a new component and render it in `PayrollSettingsPage`:

```tsx
function EmployeesSection() {
  const [employees, setEmployees] = useState<EmployeeDto[]>([])
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      setEmployees(await listEmployees())
    } catch (e: unknown) {
      message.error(e instanceof Error ? e.message : 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <Card
      title="Сотрудники"
      extra={
        <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => setAddOpen(true)}>
          Добавить
        </Button>
      }
      loading={loading}
    >
      <List
        size="small"
        dataSource={employees}
        locale={{ emptyText: 'Сотрудников пока нет' }}
        renderItem={(item) => <List.Item>{item.full_name}</List.Item>}
      />
      <EmployeeCreateModal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        onCreated={(employee) => setEmployees((prev) => [...prev, employee].sort((a, b) => a.full_name.localeCompare(b.full_name)))}
      />
    </Card>
  )
}

export function PayrollSettingsPage() {
  return (
    <>
      <PayrollDocIdFormatSection />
      <PayrollSettingsSection />
      <EmployeesSection />
    </>
  )
}
```

Replace the old `export function PayrollSettingsPage()` from the settings-relocation plan with this version (adds `<EmployeesSection />`).

- [ ] **Step 2: Type-check**

Run: `cd frontend_v2 && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 3: Manual smoke check**

Navigate to `/settings/payroll-config`, confirm a "Сотрудники" card lists existing employees and "Добавить" opens the same quick-add modal used in Task 5, and that adding one there updates the list immediately.

- [ ] **Step 4: Commit**

```bash
git add frontend_v2/src/ui/settings/PayrollSettingsPage.tsx
git commit -m "feat(settings): list and add employees on the payroll settings page"
```

---

### Task 7: `PayrollPayout` model

**Files:**
- Modify: `backend_v2/apps/modules/payroll/models.py`
- Create (generated): one migration file

**Interfaces:**
- Produces: `payroll.models.PayrollPayout` — `tenant`, `line` (FK to `PayrollLine`, `related_name="payouts"`), `cash_expense` (`OneToOneField` to `cashier.CashExpense`, `related_name="payroll_payout"`), `created_by`, `created_at`. Consumed by Task 8.

- [ ] **Step 1: Add the model**

In `backend_v2/apps/modules/payroll/models.py`, append after `PayrollLine`:

```python
class PayrollPayout(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="payroll_payouts", db_index=False)
    line = models.ForeignKey(PayrollLine, on_delete=models.PROTECT, related_name="payouts")
    cash_expense = models.OneToOneField(
        "cashier.CashExpense", on_delete=models.PROTECT, related_name="payroll_payout"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_payroll_payouts",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "payroll_payouts"

    def __str__(self) -> str:
        return f"{self.line_id}:{self.cash_expense_id}"
```

- [ ] **Step 2: Generate the migration**

Run: `make makemigrations`

Confirm (via `ls` and reading the file) it contains a single `CreateModel` for `PayrollPayout`.

- [ ] **Step 3: Write model tests**

Append to `backend_v2/apps/modules/payroll/tests.py`:

```python
from apps.modules.cashier.models import CashExpense
from apps.modules.payroll.models import PayrollPayout
from apps.modules.wallets.models import CashRegister, Wallet


class PayrollPayoutModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PayoutModelAcme", subdomain="payout-model-acme", is_active=True)
        self.user = User.objects.create_user(username="payout-model-user", password="x")
        self.doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        self.employee = Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        self.line = PayrollLine.objects.create(
            document=self.doc, line_no=1, employee=self.employee, item="Salary",
            description="", sum="1000.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=True,
        )
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main")
        self.wallet = Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=cash_register,
        )

    def test_can_create_payout_linked_to_line_and_cash_expense(self):
        expense = CashExpense.objects.create(
            tenant=self.tenant, external_id="test-1", amount="400.00", currency="UZS",
            expense_at=timezone.now(), expense_year=2026, expense_month=1, expense_day=1,
            created_by=self.user, wallet=self.wallet,
        )
        payout = PayrollPayout.objects.create(
            tenant=self.tenant, line=self.line, cash_expense=expense, created_by=self.user,
        )
        self.assertEqual(self.line.payouts.count(), 1)
        self.assertEqual(payout.cash_expense_id, expense.id)

    def test_one_cash_expense_can_back_at_most_one_payout(self):
        expense = CashExpense.objects.create(
            tenant=self.tenant, external_id="test-2", amount="400.00", currency="UZS",
            expense_at=timezone.now(), expense_year=2026, expense_month=1, expense_day=1,
            created_by=self.user, wallet=self.wallet,
        )
        PayrollPayout.objects.create(tenant=self.tenant, line=self.line, cash_expense=expense, created_by=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PayrollPayout.objects.create(tenant=self.tenant, line=self.line, cash_expense=expense, created_by=self.user)
```

`IntegrityError`/`transaction` are already imported in this file from Task 1's edits — reuse them, don't re-import.

- [ ] **Step 4: Push and verify via CI**

Push, confirm "Backend Tests" passes.

- [ ] **Step 5: Commit**

```bash
git add backend_v2/apps/modules/payroll/models.py backend_v2/apps/modules/payroll/migrations/ backend_v2/apps/modules/payroll/tests.py
git commit -m "feat(payroll): add PayrollPayout model linking a line to a CashExpense"
```

---

### Task 8: Payout service + API (single + bulk)

**Files:**
- Modify: `backend_v2/apps/modules/payroll/services.py`
- Modify: `backend_v2/apps/modules/payroll/serializers.py`
- Modify: `backend_v2/apps/modules/payroll/views.py`
- Modify: `backend_v2/apps/modules/payroll/urls.py`
- Test: `backend_v2/apps/modules/payroll/tests.py`

**Interfaces:**
- Produces: `create_payroll_line_payout(*, line, amount, actor_user) -> PayrollPayout`, `create_payroll_line_payouts_bulk(*, payouts: list[dict], actor_user, tenant) -> list[PayrollPayout]` in `payroll/services.py`. `POST /api/payroll/lines/<line_id>/payouts/`, `POST /api/payroll/lines/payouts/bulk/`.

- [ ] **Step 1: Add the service functions**

In `backend_v2/apps/modules/payroll/services.py`, extend the existing imports at the top:

```python
from decimal import Decimal
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.cashier.models import CashExpense
from apps.modules.payroll.constants import SALARY_CATEGORY
from apps.modules.payroll.models import PayrollDocument, PayrollLine, PayrollPayout
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import _recalculate_request_status, route_request_approvals
from apps.modules.requests.models import Request
from apps.modules.wallets.serializer_integration import assign_wallet_for_cash_movement
from apps.tenants.models import TenantModuleConfig
```

(`get_user_model`, `transaction`, `Sum`, `timezone`, `SALARY_CATEGORY`, `PayrollDocument`, `PayrollLine`, `create_approval_rows_for_request`, `_recalculate_request_status`, `route_request_approvals`, `Request` already exist in this file — only add what's missing: `Decimal`, `uuid4`, `ValidationError`, `CashExpense`, `PayrollPayout` (extend the existing `payroll.models` import), `assign_wallet_for_cash_movement`, `TenantModuleConfig`.)

Append at the end of the file:

```python
def _is_cash_module_enabled(*, tenant) -> bool:
    return TenantModuleConfig.objects.filter(tenant=tenant, module_key="cash", is_enabled=True).exists()


def _payroll_request_for_document(*, tenant, document_id):
    return Request.objects.filter(
        tenant=tenant,
        expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
        expense_ref_id=document_id,
    ).first()


def _paid_so_far(line: PayrollLine) -> Decimal:
    agg = PayrollPayout.objects.filter(line=line).aggregate(s=Sum("cash_expense__amount"))
    return agg.get("s") or Decimal("0")


def _validate_payout(*, line: PayrollLine, amount: Decimal) -> None:
    tenant = line.document.tenant
    request_obj = _payroll_request_for_document(tenant=tenant, document_id=line.document_id)
    if request_obj is None or request_obj.status != Request.STATUS_PAYED:
        raise ValidationError(
            {"detail": "Выплата возможна только после полного согласования заявки на весь документ."}
        )
    if not _is_cash_module_enabled(tenant=tenant):
        raise ValidationError({"detail": "Модуль кассы отключён для этой компании."})
    if amount <= 0:
        raise ValidationError({"amount": "Сумма выплаты должна быть больше нуля."})
    remaining = line.sum - _paid_so_far(line)
    if amount > remaining:
        raise ValidationError({"amount": f"Сумма превышает остаток по строке ({remaining})."})


def create_payroll_line_payout(*, line: PayrollLine, amount: Decimal, actor_user) -> PayrollPayout:
    """Records one actual cash disbursement against an accrual line. Requires the
    line's document to have a linked Request already fully approved (status=PAYED) —
    the payout itself needs no further approval. Blocks any amount that would push the
    line's total payouts past its accrued sum."""
    with transaction.atomic():
        locked_line = (
            PayrollLine.objects.select_related("document__tenant", "employee")
            .select_for_update()
            .get(pk=line.pk)
        )
        _validate_payout(line=locked_line, amount=amount)

        tenant = locked_line.document.tenant
        attrs = {"currency": Request.CURRENCY_UZS, "wallet": None}
        attrs = assign_wallet_for_cash_movement(instance=None, tenant=tenant, attrs=attrs)
        now_dt = timezone.now()
        expense = CashExpense.objects.create(
            tenant=tenant,
            external_id=f"payroll-payout-{locked_line.id}-{uuid4().hex[:8]}",
            confirmed=True,
            title=f"ЗП: {locked_line.employee.full_name}",
            amount=amount,
            currency=Request.CURRENCY_UZS,
            expense_at=now_dt,
            expense_year=now_dt.year,
            expense_month=now_dt.month,
            expense_day=now_dt.day,
            note="",
            payload={"payroll_line_id": locked_line.id, "source": "payroll_payout"},
            created_by=actor_user,
            wallet=attrs["wallet"],
        )
        return PayrollPayout.objects.create(
            tenant=tenant,
            line=locked_line,
            cash_expense=expense,
            created_by=actor_user,
        )


def create_payroll_line_payouts_bulk(*, payouts: list[dict], actor_user, tenant) -> list[PayrollPayout]:
    """All-or-nothing: pre-validates every requested (line_id, amount) pair and raises
    with a full per-line error map if any fail, before creating anything. The actual
    creation still re-validates each line under its own row lock (via
    create_payroll_line_payout), so a race that slips past the pre-check is still
    caught there and rolls back the whole batch."""
    line_ids = [p["line_id"] for p in payouts]
    lines = {
        ln.id: ln
        for ln in PayrollLine.objects.filter(
            id__in=line_ids, document__tenant=tenant
        ).select_related("document__tenant", "employee")
    }

    errors: dict[str, list[str]] = {}
    for item in payouts:
        line = lines.get(item["line_id"])
        if line is None:
            errors[str(item["line_id"])] = ["Строка не найдена."]
            continue
        try:
            _validate_payout(line=line, amount=item["amount"])
        except ValidationError as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                errors[str(item["line_id"])] = [str(v) for values in detail.values() for v in values]
            else:
                errors[str(item["line_id"])] = [str(detail)]

    if errors:
        raise ValidationError({"payouts": errors})

    with transaction.atomic():
        return [
            create_payroll_line_payout(line=lines[item["line_id"]], amount=item["amount"], actor_user=actor_user)
            for item in payouts
        ]
```

- [ ] **Step 2: Add payout serializers**

Append to `backend_v2/apps/modules/payroll/serializers.py`:

```python
class PayrollLinePayoutCreateSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Сумма должна быть больше нуля.")
        return value


class PayrollLinePayoutBulkItemSerializer(serializers.Serializer):
    line_id = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class PayrollLinePayoutBulkCreateSerializer(serializers.Serializer):
    payouts = PayrollLinePayoutBulkItemSerializer(many=True)

    def validate_payouts(self, value):
        if not value:
            raise serializers.ValidationError("Нужна хотя бы одна выплата.")
        return value


class PayrollPayoutSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    amount = serializers.DecimalField(source="cash_expense.amount", max_digits=18, decimal_places=2, read_only=True)
    created_by_full_name = serializers.SerializerMethodField()

    class Meta:
        from apps.modules.payroll.models import PayrollPayout

        model = PayrollPayout
        fields = ["id", "line_id", "amount", "created_at", "created_by", "created_by_full_name"]
        read_only_fields = fields

    def get_created_by_full_name(self, obj):
        # Same fallback convention as apps.modules.requests.serializers.RequestCommentSerializer.
        full_name = (getattr(obj.created_by, "full_name", "") or "").strip()
        return full_name or getattr(obj.created_by, "username", "")
```

(The `PayrollPayout` import is placed inside `Meta` deliberately — it's only needed there, and this file's top-level import of `payroll.models` predates Task 7's model in this same plan; adding it inline avoids reshuffling the earlier import line. If preferred, it is equally correct to instead add `PayrollPayout` to the top-level `from apps.modules.payroll.models import Employee, PayrollDocument, PayrollLine` line — either way works, just pick one and be consistent.)

- [ ] **Step 3: Add the views**

In `backend_v2/apps/modules/payroll/views.py`, add `from rest_framework.views import APIView` to the imports, extend the serializers import with `PayrollLinePayoutBulkCreateSerializer, PayrollLinePayoutCreateSerializer, PayrollPayoutSerializer`, extend the services import with `create_payroll_line_payout, create_payroll_line_payouts_bulk`, and append:

```python
class PayrollLinePayoutCreateView(generics.CreateAPIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]
    serializer_class = PayrollLinePayoutCreateSerializer

    def create(self, request, *args, **kwargs):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        line = PayrollLine.objects.filter(pk=self.kwargs["line_id"], document__tenant=tenant).first()
        if line is None:
            return Response({"detail": "Строка начисления не найдена."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = create_payroll_line_payout(
            line=line, amount=serializer.validated_data["amount"], actor_user=request.user,
        )
        out = PayrollPayoutSerializer(payout)
        return Response(out.data, status=status.HTTP_201_CREATED)


class PayrollLinePayoutBulkView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def post(self, request, *args, **kwargs):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        serializer = PayrollLinePayoutBulkCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payouts = create_payroll_line_payouts_bulk(
            payouts=serializer.validated_data["payouts"], actor_user=request.user, tenant=tenant,
        )
        out = PayrollPayoutSerializer(payouts, many=True)
        return Response(out.data, status=status.HTTP_201_CREATED)
```

- [ ] **Step 4: Wire up URLs**

In `backend_v2/apps/modules/payroll/urls.py`, extend the views import with `PayrollLinePayoutBulkView, PayrollLinePayoutCreateView` and add before `include(router.urls)`:

```python
    path("lines/payouts/bulk/", PayrollLinePayoutBulkView.as_view(), name="payroll-line-payouts-bulk"),
    path("lines/<int:line_id>/payouts/", PayrollLinePayoutCreateView.as_view(), name="payroll-line-payouts-create"),
```

(Order matters: `lines/payouts/bulk/` must be registered before `lines/<int:line_id>/payouts/`, otherwise Django's URL resolver would never reach the exact-path bulk route — `payouts` is not an integer so it wouldn't actually match `<int:line_id>` here regardless, but keeping the more specific literal path first is the same defensive convention already used for `documents/create/` vs the router's `documents/<pk>/`.)

- [ ] **Step 5: Write tests**

Append to `backend_v2/apps/modules/payroll/tests.py`. This needs a helper to get a payroll document into a `PAYED`-request state without going through the full approval chain UI — build the `Request` directly:

```python
from apps.modules.payroll.services import create_payroll_line_payout, create_payroll_line_payouts_bulk


def _make_payed_payroll_request(tenant, document, user):
    return Request.objects.create(
        tenant=tenant,
        created_by=user,
        requester=user,
        title="",
        description="",
        amount=document.lines.aggregate(s=Sum("sum")).get("s") or Decimal("0"),
        currency=Request.CURRENCY_UZS,
        payment_type=Request.PAYMENT_TYPE_PAYROLL,
        payment_purpose=SALARY_CATEGORY,
        submitted_at=timezone.now(),
        status=Request.STATUS_PAYED,
        billing_date=timezone.now().date(),
        expense_ref_id=document.pk,
        expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL,
    )


class PayrollLinePayoutServiceTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PayoutSvcAcme", subdomain="payout-svc-acme", is_active=True)
        self.user = User.objects.create_user(username="payout-svc-user", password="x")
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main")
        Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=cash_register,
        )
        self.doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        self.employee = Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        self.line = PayrollLine.objects.create(
            document=self.doc, line_no=1, employee=self.employee, item="Salary",
            description="", sum="1000.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=True,
        )

    def test_blocks_payout_before_request_is_payed(self):
        with self.assertRaises(ValidationError):
            create_payroll_line_payout(line=self.line, amount=Decimal("100.00"), actor_user=self.user)

    def test_blocks_payout_when_cash_module_disabled(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="cash").update(is_enabled=False)
        _make_payed_payroll_request(self.tenant, self.doc, self.user)
        with self.assertRaises(ValidationError):
            create_payroll_line_payout(line=self.line, amount=Decimal("100.00"), actor_user=self.user)

    def test_partial_payout_accumulates_correctly(self):
        _make_payed_payroll_request(self.tenant, self.doc, self.user)
        create_payroll_line_payout(line=self.line, amount=Decimal("300.00"), actor_user=self.user)
        create_payroll_line_payout(line=self.line, amount=Decimal("200.00"), actor_user=self.user)
        self.line.refresh_from_db()
        paid = self.line.payouts.aggregate(s=Sum("cash_expense__amount")).get("s")
        self.assertEqual(paid, Decimal("500.00"))

    def test_blocks_overpay_past_remaining(self):
        _make_payed_payroll_request(self.tenant, self.doc, self.user)
        create_payroll_line_payout(line=self.line, amount=Decimal("900.00"), actor_user=self.user)
        with self.assertRaises(ValidationError):
            create_payroll_line_payout(line=self.line, amount=Decimal("200.00"), actor_user=self.user)
        paid = self.line.payouts.aggregate(s=Sum("cash_expense__amount")).get("s")
        self.assertEqual(paid, Decimal("900.00"))

    def test_successful_payout_creates_cash_expense_with_correct_amount_and_wallet(self):
        _make_payed_payroll_request(self.tenant, self.doc, self.user)
        payout = create_payroll_line_payout(line=self.line, amount=Decimal("400.00"), actor_user=self.user)
        self.assertEqual(payout.cash_expense.amount, Decimal("400.00"))
        self.assertEqual(payout.cash_expense.wallet.wallet_type, Wallet.Type.CASH)
        self.assertEqual(payout.cash_expense.tenant_id, self.tenant.id)

    def test_bulk_payout_all_succeed(self):
        line2 = PayrollLine.objects.create(
            document=self.doc, line_no=2, employee=Employee.objects.create(tenant=self.tenant, full_name="Bob Jones"),
            item="Salary", description="", sum="500.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=True,
        )
        _make_payed_payroll_request(self.tenant, self.doc, self.user)
        results = create_payroll_line_payouts_bulk(
            payouts=[
                {"line_id": self.line.id, "amount": Decimal("1000.00")},
                {"line_id": line2.id, "amount": Decimal("500.00")},
            ],
            actor_user=self.user,
            tenant=self.tenant,
        )
        self.assertEqual(len(results), 2)

    def test_bulk_payout_rolls_back_all_if_one_line_invalid(self):
        line2 = PayrollLine.objects.create(
            document=self.doc, line_no=2, employee=Employee.objects.create(tenant=self.tenant, full_name="Bob Jones"),
            item="Salary", description="", sum="500.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=True,
        )
        _make_payed_payroll_request(self.tenant, self.doc, self.user)
        with self.assertRaises(ValidationError) as ctx:
            create_payroll_line_payouts_bulk(
                payouts=[
                    {"line_id": self.line.id, "amount": Decimal("1000.00")},
                    {"line_id": line2.id, "amount": Decimal("999999.00")},  # exceeds line2's remaining
                ],
                actor_user=self.user,
                tenant=self.tenant,
            )
        self.assertIn(str(line2.id), ctx.exception.detail["payouts"])
        self.assertEqual(PayrollPayout.objects.filter(line__document=self.doc).count(), 0)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class PayrollLinePayoutApiTests(APITestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="PayoutApiAcme", subdomain="payout-api-acme", is_active=True)
        self.user = User.objects.create_user(username="payout-api-user", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=self.user, role=TenantUserRole.ROLE_ACCOUNTANT)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="payroll", is_enabled=True)
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="cash", is_enabled=True)
        cash_register = CashRegister.objects.create(tenant=self.tenant, currency="UZS", name="Main")
        Wallet.objects.create(
            tenant=self.tenant, wallet_type=Wallet.Type.CASH, currency="UZS", cash_register=cash_register,
        )
        self.host = "payout-api-acme.example.com"
        self.doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        self.employee = Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        self.line = PayrollLine.objects.create(
            document=self.doc, line_no=1, employee=self.employee, item="Salary",
            description="", sum="1000.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=True,
        )
        _make_payed_payroll_request(self.tenant, self.doc, self.user)

    def test_create_payout_via_api(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            f"/api/payroll/lines/{self.line.id}/payouts/", {"amount": "400.00"}, format="json", HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(Decimal(str(res.data["amount"])), Decimal("400.00"))

    def test_create_payout_over_remaining_returns_400(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            f"/api/payroll/lines/{self.line.id}/payouts/", {"amount": "5000.00"}, format="json", HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 400)

    def test_bulk_create_payouts_via_api(self):
        self.client.force_authenticate(self.user)
        res = self.client.post(
            "/api/payroll/lines/payouts/bulk/",
            {"payouts": [{"line_id": self.line.id, "amount": "1000.00"}]},
            format="json",
            HTTP_HOST=self.host,
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(len(res.data), 1)
```

Add `from rest_framework.exceptions import ValidationError` to `tests.py` imports if not already present (needed by `PayrollLinePayoutServiceTests`).

- [ ] **Step 6: Push and verify via CI**

Push, confirm "Backend Tests" passes.

- [ ] **Step 7: Commit**

```bash
git add backend_v2/apps/modules/payroll/services.py backend_v2/apps/modules/payroll/serializers.py backend_v2/apps/modules/payroll/views.py backend_v2/apps/modules/payroll/urls.py backend_v2/apps/modules/payroll/tests.py
git commit -m "feat(payroll): add cash payout service and single/bulk API endpoints"
```

---

## Self-Review Notes

- Spec coverage: Часть 1 (Фаза C cutover, n8n resolution, portal serializer, Employee API) — Tasks 1-4, 6. Часть 2 (`PayrollPayout`, `create_payroll_line_payout`, single + bulk API, partial-payout accumulation, overpay block, PAYED-gate, cash-module gate) — Tasks 7-8. Frontend employee picker with quick-add — Task 5.
- No placeholders: every task gives full code for every file touched; no "add error handling" or "similar to Task N" shortcuts.
- Type consistency: `create_payroll_line_payout(*, line, amount, actor_user)` signature is identical everywhere it's called (Task 8 service, views, tests). `PayrollLineSerializer.get_employee` shape (`{"id", "full_name"}`) matches what Task 5/6 frontend code expects to consume once wired into `PayrollDocumentDetailPage.tsx` in the next plan. `PayrollPayoutSerializer` fields (`id, line_id, amount, created_at, created_by`) match what the payout-UI plan will render.
- The "race condition" scenario from the spec's test list is covered here only as a **sequential** accumulation/overpay test (`test_partial_payout_accumulates_correctly`, `test_blocks_overpay_past_remaining`) — `select_for_update()` is what actually prevents a true concurrent race in production; Django's `TestCase` runs inside a single wrapping transaction and cannot exercise genuine concurrent DB access, so no test here claims to reproduce the race itself, only the accounting invariant the lock protects.
