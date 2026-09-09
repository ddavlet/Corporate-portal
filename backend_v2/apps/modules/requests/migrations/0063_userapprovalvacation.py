from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0062_alter_request_expense_ref_target"),
        ("tenants", "0025_tenant_create_payment_request_on_payroll_accrual"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserApprovalVacation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("snapshot", models.JSONField(blank=True, default=list)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_approval_vacations",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approval_vacations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "user_approval_vacations",
                "indexes": [
                    models.Index(fields=["tenant", "user", "ended_at"], name="user_appr_vacation_active_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(ended_at__isnull=True),
                        fields=("tenant", "user"),
                        name="user_appr_vacation_one_active_uniq",
                    ),
                ],
            },
        ),
    ]
