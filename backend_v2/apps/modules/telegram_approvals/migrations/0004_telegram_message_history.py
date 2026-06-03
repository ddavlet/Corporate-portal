"""
Add resend tracking columns to telegram_messages and create telegram_message_history.

All database operations are idempotent (ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS)
so the migration is safe to re-run after a partial deploy.
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("telegram_approvals", "0003_notification"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── 1. Add resend tracking columns to telegram_messages ─────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="telegrammessage",
                    name="resend_count",
                    field=models.PositiveSmallIntegerField(default=0),
                ),
                migrations.AddField(
                    model_name="telegrammessage",
                    name="last_resend_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE telegram_messages
                            ADD COLUMN IF NOT EXISTS resend_count smallint NOT NULL DEFAULT 0,
                            ADD COLUMN IF NOT EXISTS last_resend_at timestamptz NULL;
                    """,
                    reverse_sql="""
                        ALTER TABLE telegram_messages
                            DROP COLUMN IF EXISTS resend_count,
                            DROP COLUMN IF EXISTS last_resend_at;
                    """,
                ),
            ],
        ),

        # ── 2. Create telegram_message_history ───────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="TelegramMessageHistory",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("action", models.CharField(
                            choices=[
                                ("send", "Send (initial dispatch)"),
                                ("edit", "Edit (card updated)"),
                                ("deactivate", "Deactivate (buttons removed)"),
                                ("resend_old", "Resend — old card deactivated"),
                                ("resend_new", "Resend — new card sent"),
                                ("callback", "Callback (button pressed in Telegram)"),
                                ("delete", "Delete"),
                            ],
                            max_length=20,
                        )),
                        ("message_id", models.BigIntegerField(blank=True, null=True)),
                        ("recipient_id", models.CharField(blank=True, max_length=50)),
                        ("external_user_id", models.BigIntegerField(blank=True, null=True)),
                        ("text", models.TextField(blank=True)),
                        ("buttons", models.JSONField(blank=True, null=True)),
                        ("request_payload", models.JSONField(blank=True, null=True)),
                        ("response_payload", models.JSONField(blank=True, null=True)),
                        ("success", models.BooleanField(default=True)),
                        ("error_message", models.TextField(blank=True)),
                        ("actor_external_user_id", models.BigIntegerField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "telegram_message",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="history",
                                to="telegram_approvals.telegrammessage",
                            ),
                        ),
                        (
                            "actor_user",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="telegram_message_history_actions",
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "telegram_message_history",
                        "ordering": ["created_at"],
                        "indexes": [
                            models.Index(fields=["telegram_message", "created_at"], name="tgmsghistory_msg_created_idx"),
                            models.Index(fields=["message_id"], name="tgmsghistory_message_id_idx"),
                            models.Index(fields=["action"], name="tgmsghistory_action_idx"),
                        ],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS telegram_message_history (
                            id bigserial PRIMARY KEY,
                            action varchar(20) NOT NULL,
                            message_id bigint NULL,
                            recipient_id varchar(50) NOT NULL DEFAULT '',
                            external_user_id bigint NULL,
                            text text NOT NULL DEFAULT '',
                            buttons jsonb NULL,
                            request_payload jsonb NULL,
                            response_payload jsonb NULL,
                            success boolean NOT NULL DEFAULT true,
                            error_message text NOT NULL DEFAULT '',
                            actor_external_user_id bigint NULL,
                            created_at timestamptz NOT NULL,
                            telegram_message_id bigint NOT NULL
                                REFERENCES telegram_messages(id)
                                ON DELETE CASCADE
                                DEFERRABLE INITIALLY DEFERRED,
                            actor_user_id bigint NULL
                                REFERENCES accounts_user(id)
                                ON DELETE SET NULL
                                DEFERRABLE INITIALLY DEFERRED
                        );
                        CREATE INDEX IF NOT EXISTS tgmsghistory_msg_created_idx
                            ON telegram_message_history (telegram_message_id, created_at);
                        CREATE INDEX IF NOT EXISTS tgmsghistory_message_id_idx
                            ON telegram_message_history (message_id);
                        CREATE INDEX IF NOT EXISTS tgmsghistory_action_idx
                            ON telegram_message_history (action);
                    """,
                    reverse_sql="DROP TABLE IF EXISTS telegram_message_history;",
                ),
            ],
        ),
    ]
