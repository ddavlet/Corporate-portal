from datetime import date

from django.db import migrations, models


def _backfill_amortization_start_date(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    for row in Request.objects.filter(amortization_start_date__isnull=True).only("id", "billing_date"):
        if row.billing_date is None:
            continue
        row.amortization_start_date = date(row.billing_date.year, row.billing_date.month, 1)
        row.save(update_fields=["amortization_start_date"])


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0030_approval_canceled_and_resend_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="request",
            name="amortization_months",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="request",
            name="amortization_start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(_backfill_amortization_start_date, migrations.RunPython.noop),
    ]
