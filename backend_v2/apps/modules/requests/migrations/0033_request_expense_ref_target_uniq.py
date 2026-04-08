from django.db import migrations, models

from apps.modules.payroll.constants import SALARY_CATEGORY


def _backfill_expense_ref_target(apps, schema_editor):
    Req = apps.get_model("requests", "Request")
    CASH = "Наличные"
    TRANSFER = "Перечисление"
    TOPUP = "Пополнение"
    CARD = "Платежная карта"
    for row in Req.objects.exclude(expense_ref_id__isnull=True).iterator():
        pt = row.payment_type
        cat = (row.category or "").strip()
        if pt == CASH and cat == SALARY_CATEGORY:
            target = "payroll"
        elif pt == CASH:
            target = "cash"
        elif pt in (TRANSFER, TOPUP):
            target = "bank"
        elif pt == CARD:
            target = "card"
        else:
            target = None
        row.expense_ref_target = target
        row.save(update_fields=["expense_ref_target"])


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0032_request_expense_ref_id"),
    ]

    operations = [
        migrations.AddField(
            model_name="request",
            name="expense_ref_target",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cash", "cash"),
                    ("payroll", "payroll"),
                    ("bank", "bank"),
                    ("card", "card"),
                ],
                max_length=16,
                null=True,
            ),
        ),
        migrations.RunPython(_backfill_expense_ref_target, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="request",
            constraint=models.UniqueConstraint(
                condition=models.Q(expense_ref_id__isnull=False, expense_ref_target__isnull=False),
                fields=("tenant", "expense_ref_target", "expense_ref_id"),
                name="req_tenant_exp_ref_target_id_uniq",
            ),
        ),
    ]
