import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("tenants", "0020_tenant_cash_expense_external_id_format"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantReportSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pnl_config", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="report_settings",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "tenant_report_settings",
            },
        ),
    ]
