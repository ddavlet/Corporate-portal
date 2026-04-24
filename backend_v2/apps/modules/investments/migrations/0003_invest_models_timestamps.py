import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models


def backfill_investreturn_last_edit_at(apps, schema_editor):
    InvestReturn = apps.get_model("investments", "InvestReturn")
    for row in InvestReturn.objects.all().only("id", "created_at", "last_edit_at").iterator():
        if row.last_edit_at is None:
            row.last_edit_at = row.created_at
            row.save(update_fields=["last_edit_at"])


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0002_investreturn_sum_uzs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="investreturn",
            name="last_edit_at",
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.RunPython(backfill_investreturn_last_edit_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="investreturn",
            name="last_edit_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name="InvestPayoutSchedule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payout_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "currency",
                    models.CharField(default="USD", max_length=3),
                ),
                ("is_paid", models.BooleanField(default=False)),
                (
                    "payment_amount",
                    models.DecimalField(decimal_places=2, default=Decimal("0.00"), max_digits=18),
                ),
                ("comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_edit_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_invest_payout_schedules",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invest_payout_schedules",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "invest_payout_schedules",
                "ordering": ["-payout_date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="ProjectInvestment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("comment", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_edit_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_project_investments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_investments",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "project_investments",
                "ordering": ["-date", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="investpayoutschedule",
            index=models.Index(fields=["tenant", "payout_date"], name="invsched_tenant_date_idx"),
        ),
        migrations.AddIndex(
            model_name="investpayoutschedule",
            index=models.Index(fields=["tenant", "is_paid"], name="invsched_tenant_paid_idx"),
        ),
        migrations.AddIndex(
            model_name="projectinvestment",
            index=models.Index(fields=["tenant", "date"], name="invproj_tenant_date_idx"),
        ),
    ]
