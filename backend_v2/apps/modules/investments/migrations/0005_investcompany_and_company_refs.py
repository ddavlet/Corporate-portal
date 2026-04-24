import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0004_projectinvestment_currency"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestCompany",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("comment", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_edit_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_invest_companies",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invest_companies",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "invest_companies",
                "ordering": ["name", "id"],
                "unique_together": {("tenant", "name")},
            },
        ),
        migrations.AddField(
            model_name="investpayoutschedule",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payout_schedules",
                to="investments.investcompany",
            ),
        ),
        migrations.AddField(
            model_name="investreturn",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="returns",
                to="investments.investcompany",
            ),
        ),
        migrations.AddField(
            model_name="projectinvestment",
            name="company",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="project_investments",
                to="investments.investcompany",
            ),
        ),
        migrations.AddIndex(
            model_name="investcompany",
            index=models.Index(fields=["tenant", "is_active"], name="invco_tenant_active_idx"),
        ),
    ]
