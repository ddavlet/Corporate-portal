from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0010_request_status_choices"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="Approval",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("approver_tg_id", models.BigIntegerField(blank=True, null=True)),
                        ("message_id", models.BigIntegerField(blank=True, null=True)),
                        ("message_sent", models.BooleanField(default=False)),
                        ("step", models.IntegerField(default=1)),
                        (
                            "step_type",
                            models.CharField(
                                choices=[("serial", "serial"), ("payment", "payment")],
                                default="serial",
                                max_length=10,
                            ),
                        ),
                        (
                            "decision",
                            models.CharField(
                                choices=[("pending", "pending"), ("approved", "approved"), ("rejected", "rejected")],
                                default="pending",
                                max_length=12,
                            ),
                        ),
                        ("comment", models.TextField(blank=True, null=True)),
                        ("decided_at", models.DateTimeField(blank=True, null=True)),
                        (
                            "approver_user",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.PROTECT,
                                related_name="request_approvals",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                        (
                            "request",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="approvals",
                                to="requests.request",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "approvals",
                        "indexes": [
                            models.Index(fields=["request"], name="approvals_request_id_idx"),
                            models.Index(fields=["decision"], name="approvals_decision_idx"),
                            models.Index(fields=["approver_tg_id"], name="approvals_approver_tg_id_idx"),
                            models.Index(fields=["message_sent"], name="approvals_message_sent_idx"),
                        ],
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("request", "step", "approver_user"),
                                name="approvals_request_step_approver_user_uniq",
                            )
                        ],
                    },
                ),
            ],
            database_operations=[],
        ),
    ]
