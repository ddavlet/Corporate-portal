from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0037_investment_funding_mode"),
        ("requests", "0067_request_invest_payment_types"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectInvestmentRequestLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project_investment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_links",
                        to="investments.projectinvestment",
                    ),
                ),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="investment_links",
                        to="requests.request",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_investment_request_links",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "project_investment_request_links",
                "ordering": ["id"],
                "indexes": [models.Index(fields=["tenant", "request"], name="invpireq_tenant_req_idx")],
            },
        ),
    ]
