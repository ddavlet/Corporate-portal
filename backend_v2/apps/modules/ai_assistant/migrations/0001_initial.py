import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0026_tenant_payroll_payout_mode"),
        ("telegram_approvals", "0006_drop_redundant_indexes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChainNode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chat_id", models.CharField(max_length=50)),
                ("message_id", models.BigIntegerField()),
                ("parent_message_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("user", "Спрашивающий (допущенный)"),
                            ("member", "Другой участник цепочки"),
                            ("bot_agent", "Ответ агента"),
                            ("bot_auto", "Автосообщение бота"),
                        ],
                        max_length=20,
                    ),
                ),
                ("author_tg_id", models.BigIntegerField(blank=True, null=True)),
                ("author_label", models.CharField(blank=True, default="", max_length=255)),
                ("author_roles", models.CharField(blank=True, default="", max_length=100)),
                ("text", models.TextField(blank=True, default="")),
                ("agent_messages", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "author_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_chain_nodes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_chain_nodes",
                        to="tenants.tenant",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="PendingConfirmation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chat_id", models.CharField(max_length=50)),
                ("requester_tg_id", models.BigIntegerField()),
                ("origin_message_id", models.BigIntegerField()),
                ("agent_messages", models.JSONField()),
                ("tool_calls", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Ожидает"),
                            ("confirmed", "Подтверждено"),
                            ("cancelled", "Отменено"),
                            ("expired", "Истекло"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("expires_at", models.DateTimeField()),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "confirmation_message",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_pending_confirmations",
                        to="telegram_approvals.telegrammessage",
                    ),
                ),
                (
                    "requester_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_pending_confirmations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_pending_confirmations",
                        to="tenants.tenant",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="UsageRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("chat_id", models.CharField(max_length=50)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("model", models.CharField(max_length=64)),
                ("input_tokens", models.PositiveIntegerField(default=0)),
                ("output_tokens", models.PositiveIntegerField(default=0)),
                ("cache_read_tokens", models.PositiveIntegerField(default=0)),
                ("cache_creation_tokens", models.PositiveIntegerField(default=0)),
                ("cost_usd", models.DecimalField(decimal_places=6, default=0, max_digits=12)),
                ("mcp_calls", models.PositiveSmallIntegerField(default=0)),
                ("duration_ms", models.PositiveIntegerField(default=0)),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("answered", "Ответ"),
                            ("confirmation_requested", "Запрошено подтверждение"),
                            ("refused", "Отказ"),
                            ("error", "Ошибка"),
                        ],
                        max_length=30,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ai_usage_records",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="ai_usage_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="chainnode",
            constraint=models.UniqueConstraint(
                fields=("tenant", "chat_id", "message_id"), name="aia_node_tenant_chat_msg_uniq"
            ),
        ),
        migrations.AddIndex(
            model_name="chainnode",
            index=models.Index(fields=["tenant", "chat_id", "parent_message_id"], name="aia_node_parent_idx"),
        ),
        migrations.AddIndex(
            model_name="chainnode",
            index=models.Index(fields=["created_at"], name="aia_node_created_idx"),
        ),
        migrations.AddIndex(
            model_name="pendingconfirmation",
            index=models.Index(fields=["tenant", "status"], name="aia_pending_tenant_status_idx"),
        ),
        migrations.AddIndex(
            model_name="usagerecord",
            index=models.Index(fields=["tenant", "created_at"], name="aia_usage_tenant_created_idx"),
        ),
    ]
