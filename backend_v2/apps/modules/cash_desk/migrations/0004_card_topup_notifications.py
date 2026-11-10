# Hand-written: card top-up notification settings and per-recipient message log

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cash_desk", "0003_transfer_target_source_snapshot"),
        ("requests", "0067_request_invest_payment_types"),
        ("telegram_approvals", "0006_drop_redundant_indexes"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CardTopupNotifyConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "recipients",
                    models.ManyToManyField(
                        blank=True,
                        related_name="card_topup_notify_configs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_topup_notify_config",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_card_topup_notify_configs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "cash_desk_card_topup_configs"},
        ),
        migrations.CreateModel(
            name="CardTopupNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Ожидает"),
                            ("sent", "Отправлено"),
                            ("failed", "Ошибка"),
                            ("skipped", "Пропущено"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("error", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_topup_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "request",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="card_topup_notifications",
                        to="requests.request",
                    ),
                ),
                (
                    "telegram_message",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="card_topup_notification",
                        to="telegram_approvals.telegrammessage",
                    ),
                ),
            ],
            options={
                "db_table": "cash_desk_card_topup_notifications",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("request", "recipient"), name="cash_desk_card_topup_request_recipient_uniq"
                    )
                ],
            },
        ),
    ]
