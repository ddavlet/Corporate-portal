from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0007_remove_extra_tenant_integration_fields"),
        ("investments", "0005_investcompany_and_company_refs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestPayoutScheduleShareLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("paid_filter", models.CharField(choices=[("all", "All"), ("paid", "Paid"), ("unpaid", "Unpaid")], default="all", max_length=10)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="schedule_share_links",
                        to="investments.investcompany",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_invest_schedule_share_links",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invest_schedule_share_links",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "invest_payout_schedule_share_links",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="investpayoutschedulesharelink",
            index=models.Index(fields=["tenant", "is_active"], name="invslink_tenant_active_idx"),
        ),
        migrations.AddIndex(
            model_name="investpayoutschedulesharelink",
            index=models.Index(fields=["tenant", "company"], name="invslink_tenant_comp_idx"),
        ),
    ]
