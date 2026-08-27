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
    PayrollLine.objects.filter(employee_fk__isnull=False).update(employee_fk=None)


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0004_employee_payrollline_employee_fk_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_employees, backwards),
    ]
