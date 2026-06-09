"""
Create telegram_chat_registry and telegram_events tables.

All database operations use CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
so the migration is safe to re-run after a partial deploy.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("telegram_approvals", "0004_telegram_message_history"),
    ]

    operations = [
        # ── 1. TelegramChatRegistry ───────────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="TelegramChatRegistry",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("chat_id", models.CharField(max_length=50, unique=True)),
                        ("chat_type", models.CharField(blank=True, max_length=20)),
                        ("name", models.CharField(blank=True, max_length=255)),
                        ("username", models.CharField(blank=True, max_length=100)),
                        ("first_seen_at", models.DateTimeField(auto_now_add=True)),
                        ("last_seen_at", models.DateTimeField(auto_now=True)),
                    ],
                    options={
                        "db_table": "telegram_chat_registry",
                        "ordering": ["-last_seen_at"],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS telegram_chat_registry (
                            id          bigserial PRIMARY KEY,
                            chat_id     varchar(50) NOT NULL,
                            chat_type   varchar(20) NOT NULL DEFAULT '',
                            name        varchar(255) NOT NULL DEFAULT '',
                            username    varchar(100) NOT NULL DEFAULT '',
                            first_seen_at timestamptz NOT NULL,
                            last_seen_at  timestamptz NOT NULL,
                            CONSTRAINT telegram_chat_registry_chat_id_key UNIQUE (chat_id)
                        );
                    """,
                    reverse_sql="DROP TABLE IF EXISTS telegram_chat_registry;",
                ),
            ],
        ),

        # ── 2. TelegramEvent ──────────────────────────────────────────────────────
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="TelegramEvent",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("chat_id", models.CharField(blank=True, max_length=50)),
                        ("event_type", models.CharField(max_length=50)),
                        ("direction", models.CharField(
                            choices=[("incoming", "Incoming"), ("outgoing", "Outgoing")],
                            max_length=10,
                        )),
                        ("timestamp", models.DateTimeField()),
                        ("payload", models.JSONField()),
                        ("update_id", models.BigIntegerField(blank=True, null=True)),
                        ("sender_id", models.BigIntegerField(blank=True, null=True)),
                        ("message_id_tg", models.BigIntegerField(blank=True, null=True)),
                        ("message_text", models.TextField(blank=True)),
                        (
                            "chat_registry",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="events",
                                to="telegram_approvals.telegramchatregistry",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "telegram_events",
                        "ordering": ["-timestamp"],
                        "indexes": [
                            models.Index(fields=["chat_id", "timestamp"], name="tgevent_chat_ts_idx"),
                            models.Index(fields=["event_type", "direction"], name="tgevent_type_dir_idx"),
                            models.Index(fields=["sender_id"], name="tgevent_sender_idx"),
                            models.Index(fields=["update_id"], name="tgevent_update_id_idx"),
                        ],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS telegram_events (
                            id            bigserial PRIMARY KEY,
                            chat_id       varchar(50) NOT NULL DEFAULT '',
                            event_type    varchar(50) NOT NULL,
                            direction     varchar(10) NOT NULL,
                            timestamp     timestamptz NOT NULL,
                            payload       jsonb NOT NULL,
                            update_id     bigint NULL,
                            sender_id     bigint NULL,
                            message_id_tg bigint NULL,
                            message_text  text NOT NULL DEFAULT '',
                            chat_registry_id bigint NULL
                                REFERENCES telegram_chat_registry(id)
                                ON DELETE SET NULL
                                DEFERRABLE INITIALLY DEFERRED
                        );
                        CREATE INDEX IF NOT EXISTS tgevent_chat_ts_idx
                            ON telegram_events (chat_id, timestamp);
                        CREATE INDEX IF NOT EXISTS tgevent_type_dir_idx
                            ON telegram_events (event_type, direction);
                        CREATE INDEX IF NOT EXISTS tgevent_sender_idx
                            ON telegram_events (sender_id);
                        CREATE INDEX IF NOT EXISTS tgevent_update_id_idx
                            ON telegram_events (update_id);
                        CREATE INDEX IF NOT EXISTS tgevent_ts_idx
                            ON telegram_events (timestamp);
                    """,
                    reverse_sql="DROP TABLE IF EXISTS telegram_events;",
                ),
            ],
        ),
    ]
