# Справочник сотрудников: схема + бэкафилл (Фазы A+B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `payroll.Employee` directory model and a temporary nullable `PayrollLine.employee_fk` field, then backfill it from the existing free-text `PayrollLine.employee` values — without changing any read/write behavior yet. This is Phase A (schema) + Phase B (data migration) of the 3-phase rollout described in the spec; Phase C (cutover to make `employee_fk` the authoritative field and remove the old text column) is a **separate** plan, deployed only after this one is verified in production.

**Architecture:** Two new migrations in `apps.modules.payroll`: a schema migration (generated via `make makemigrations`, not hand-written) adding `Employee` and the nullable `employee_fk` FK on `PayrollLine`; and a hand-written `RunPython` data migration that, per tenant, creates one `Employee` row per distinct historical `PayrollLine.employee` string and links matching rows via `employee_fk`. The old `employee` text field is untouched — nothing in the application reads `employee_fk` yet, so this is a zero-behavior-change, safe-to-deploy-anytime change.

**Tech Stack:** Django ORM, Django migrations (`RunPython` data migration).

**Spec:** `docs/superpowers/specs/2026-08-24-payroll-cash-payouts-design.md` (Часть 1, sections "Модель `payroll.Employee`" and "Миграция (3 фазы, без потери данных)" — Фаза A and Фаза B only)

## Global Constraints

- Migrations are never generated locally with `python manage.py makemigrations` — always via `make makemigrations`, which creates them on the server and downloads them locally (project rule).
- Data must never be deleted. The backfill only creates `Employee` rows and sets a currently-unused nullable FK — it does not touch or delete the existing `employee` text column.
- The data migration must be idempotent (safe to re-run) — uses `get_or_create` and only updates rows where `employee_fk` is still `NULL`.
- Iterate with `.iterator()` for any potentially large queryset per this project's migration-safety convention.
- No local test runs (`pytest`, `python manage.py test`) — tests are verified via GitHub Actions ("Backend Tests") after push.

---

### Task 1: Add `Employee` model and nullable `PayrollLine.employee_fk`

**Files:**
- Modify: `backend_v2/apps/modules/payroll/models.py`
- Create (generated, not hand-written): a new file under `backend_v2/apps/modules/payroll/migrations/` (exact name determined by `make makemigrations` in Step 2 — likely `0004_employee_payrollline_employee_fk.py` or similar; confirm the actual name in Step 3)
- Test: `backend_v2/apps/modules/payroll/tests.py`

**Interfaces:**
- Produces: `payroll.models.Employee` — `tenant` (FK), `full_name` (CharField), `created_at`, `created_by`; unique together `(tenant, full_name)`. `payroll.models.PayrollLine.employee_fk` — nullable FK to `Employee`, `related_name="payroll_lines"`. Both consumed by Task 2 (data migration) and by the later cutover plan.

- [ ] **Step 1: Add the model changes**

In `backend_v2/apps/modules/payroll/models.py`, add the new `Employee` model right before `PayrollLine` (after the `PayrollDocument` class, so `Employee` exists before `PayrollLine` references it):

```python
class Employee(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="employees", db_index=False)
    full_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_employees",
    )

    class Meta:
        db_table = "payroll_employees"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "full_name"], name="uniq_employee_tenant_full_name"),
        ]

    def __str__(self) -> str:
        return self.full_name
```

Then, in `PayrollLine`, add the temporary nullable FK right after the existing `employee = models.TextField()` line:

```python
    employee = models.TextField()
    employee_fk = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_lines",
    )
```

(The old `employee` field is left completely unchanged — do not touch it in this task.)

- [ ] **Step 2: Generate the schema migration**

Run: `make makemigrations`

This creates the migration on the server and downloads it into `backend_v2/apps/modules/payroll/migrations/`. It must contain exactly two operations: `CreateModel` for `Employee` and `AddField` for `PayrollLine.employee_fk`.

- [ ] **Step 3: Confirm the generated migration and note its filename**

Run: `ls backend_v2/apps/modules/payroll/migrations/ | sort`

Read the newest file (the one after `0003_payrolldocument_created_by_and_more.py`) and confirm it contains a `CreateModel` for `Employee` (matching the fields above) and an `AddField` for `employee_fk` on `PayrollLine` with `null=True`. Write down its exact filename (without `.py`) — Task 2 needs it as a migration dependency.

- [ ] **Step 4: Write model tests**

Add to `backend_v2/apps/modules/payroll/tests.py` (append a new test class; the file already imports `Tenant`, `TestCase`, `get_user_model` — reuse those):

```python
from django.db import IntegrityError, transaction
from apps.modules.payroll.models import Employee


class EmployeeModelTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="EmpAcme", subdomain="emp-acme", is_active=True)

    def test_can_create_employee(self):
        emp = Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        self.assertIsNotNone(emp.id)
        self.assertEqual(str(emp), "Alice Smith")

    def test_unique_full_name_per_tenant(self):
        Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")

    def test_same_full_name_allowed_in_different_tenant(self):
        other_tenant = Tenant.objects.create(name="EmpOther", subdomain="emp-other", is_active=True)
        Employee.objects.create(tenant=self.tenant, full_name="Alice Smith")
        emp2 = Employee.objects.create(tenant=other_tenant, full_name="Alice Smith")
        self.assertIsNotNone(emp2.id)

    def test_payroll_line_employee_fk_is_optional_and_links_to_employee(self):
        doc = PayrollDocument.objects.create(tenant=self.tenant, doc_id=None)
        emp = Employee.objects.create(tenant=self.tenant, full_name="Bob Jones")
        line_without_fk = PayrollLine.objects.create(
            document=doc, line_no=1, employee="Free text still works", item="Salary",
            description="", sum="100.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=False,
        )
        line_with_fk = PayrollLine.objects.create(
            document=doc, line_no=2, employee="Bob Jones", employee_fk=emp, item="Salary",
            description="", sum="200.00", days_plan=None, days_fact=None,
            period_start=None, period_end=None, approval=False,
        )
        self.assertIsNone(line_without_fk.employee_fk)
        self.assertEqual(line_with_fk.employee_fk_id, emp.id)
        self.assertEqual(emp.payroll_lines.count(), 1)
```

- [ ] **Step 5: Push and verify via CI**

This project forbids local test runs. Push the branch (`make push`) and confirm the "Backend Tests" GitHub Actions workflow passes for these new tests before continuing.

- [ ] **Step 6: Commit**

```bash
git add backend_v2/apps/modules/payroll/models.py backend_v2/apps/modules/payroll/migrations/ backend_v2/apps/modules/payroll/tests.py
git commit -m "feat(payroll): add Employee directory model and nullable PayrollLine.employee_fk"
```

---

### Task 2: Backfill `Employee` rows and `employee_fk` from historical data

**Files:**
- Create: `backend_v2/apps/modules/payroll/migrations/<next_number>_backfill_employee_from_payrollline.py` (hand-written `RunPython` migration, dependency = the migration filename noted in Task 1 Step 3)

**Interfaces:**
- Consumes: `Employee`, `PayrollLine.employee_fk` from Task 1.
- Produces: for every tenant, one `Employee` row per distinct non-blank historical `PayrollLine.employee` value, and `PayrollLine.employee_fk` populated to match.

- [ ] **Step 1: Determine the next migration number**

Run: `ls backend_v2/apps/modules/payroll/migrations/ | sort | tail -1`

Use the number after that as this migration's prefix (e.g. if Task 1 produced `0004_...py`, this one is `0005_backfill_employee_from_payrollline.py`).

- [ ] **Step 2: Write the data migration**

Create `backend_v2/apps/modules/payroll/migrations/0005_backfill_employee_from_payrollline.py` (replace `0005` with the actual number from Step 1, and replace the `dependencies` value below with the exact filename noted in Task 1 Step 3):

```python
from django.db import migrations


def backfill_employees(apps, schema_editor):
    PayrollLine = apps.get_model("payroll", "PayrollLine")
    Employee = apps.get_model("payroll", "Employee")

    pairs = (
        PayrollLine.objects
        .exclude(employee="")
        .values_list("document__tenant_id", "employee")
        .distinct()
        .iterator()
    )
    for tenant_id, employee_name in pairs:
        name = (employee_name or "").strip()
        if not name:
            continue
        employee, _ = Employee.objects.get_or_create(tenant_id=tenant_id, full_name=name)
        PayrollLine.objects.filter(
            document__tenant_id=tenant_id,
            employee=employee_name,
            employee_fk__isnull=True,
        ).update(employee_fk=employee)


def backwards(apps, schema_editor):
    # Best-effort rollback only: clear the FK, keep the Employee rows (they may already
    # be referenced elsewhere by the time a rollback happens; deleting is not safe).
    PayrollLine = apps.get_model("payroll", "PayrollLine")
    PayrollLine.objects.update(employee_fk=None)


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0004_employee_payrollline_employee_fk"),
    ]

    operations = [
        migrations.RunPython(backfill_employees, backwards),
    ]
```

- [ ] **Step 3: Push and let CI verify the migration applies cleanly**

Push the branch (`make push`) and confirm "Backend Tests" passes — this workflow applies all migrations against a fresh test database, which validates the migration runs without errors (including on an empty `PayrollLine` table).

- [ ] **Step 4: Commit**

```bash
git add backend_v2/apps/modules/payroll/migrations/
git commit -m "data(payroll): backfill Employee rows and PayrollLine.employee_fk from historical text"
```

---

## Post-Merge Manual Verification (required before starting the cutover plan)

This is **not** an automated test — after this plan is merged and deployed to production (`make deploy`), confirm the backfill actually completed on real data before starting the Phase-C cutover plan (which makes `employee_fk` mandatory and removes the old field):

1. Run `make showmigrations` and confirm both migrations from this plan show as applied.
2. Query for any unlinked rows — e.g. via `mcp__postgres-kolberg__execute_sql` or the admin: `SELECT COUNT(*) FROM payroll_lines WHERE employee_fk_id IS NULL AND employee != ''`. Expected: `0`.
3. Only once that count is `0` is it safe to proceed to the cutover plan.

## Self-Review Notes

- Spec coverage: implements Фаза A and Фаза B exactly as described in the spec's migration section. Фаза C is intentionally out of scope — it's a separate plan per the earlier "4 plans" decomposition decision.
- No placeholders: the data migration is given in full, including the defensive idempotency check (`employee_fk__isnull=True`) and the `.iterator()` usage required by this project's migration-safety convention.
- Type consistency: `Employee.full_name`, `Employee.tenant`, `PayrollLine.employee_fk` names match what the spec (and the later cutover plan) expect.
- Deliberately no automated test for the data migration itself — this matches the existing convention in this codebase (e.g. `apps/tenants/migrations/0003_backfill_tenant_admin_to_admin_role.py`, `apps/modules/requests/migrations/0055_populate_telegram_messages.py`), neither of which has a dedicated migration test. The manual verification section above is the safety net instead.
