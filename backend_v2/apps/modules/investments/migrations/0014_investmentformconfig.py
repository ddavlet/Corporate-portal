from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0013_backfill_invest_return_cbu_from_date"),
        ("tenants", "0020_tenant_cash_expense_external_id_format"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestmentFormConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("uses_companies", models.BooleanField(default=True)),
                ("allowed_return_types", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_form_config",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "investment_form_config",
            },
        ),
    ]
