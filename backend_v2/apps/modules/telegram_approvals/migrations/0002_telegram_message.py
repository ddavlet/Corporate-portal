from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("telegram_approvals", "0001_initial"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="TelegramMessage",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("recipient_id", models.CharField(max_length=50)),
                        ("external_user_id", models.BigIntegerField(blank=True, null=True)),
                        ("message_id", models.BigIntegerField()),
                        ("sent_at", models.DateTimeField()),
                        (
                            "tenant",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="telegram_messages",
                                to="tenants.tenant",
                            ),
                        ),
                    ],
                    options={"db_table": "telegram_messages"},
                ),
                migrations.AddIndex(
                    model_name="telegrammessage",
                    index=models.Index(fields=["tenant", "recipient_id"], name="tgmsg_tenant_recipient_idx"),
                ),
                migrations.AddIndex(
                    model_name="telegrammessage",
                    index=models.Index(fields=["message_id"], name="tgmsg_message_id_idx"),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS telegram_messages (
                            id bigserial PRIMARY KEY,
                            recipient_id varchar(50) NOT NULL,
                            external_user_id bigint NULL,
                            message_id bigint NOT NULL,
                            sent_at timestamptz NOT NULL,
                            tenant_id bigint NOT NULL
                                REFERENCES tenants_tenant(id)
                                ON DELETE CASCADE
                                DEFERRABLE INITIALLY DEFERRED
                        );
                        CREATE INDEX IF NOT EXISTS tgmsg_tenant_recipient_idx
                            ON telegram_messages (tenant_id, recipient_id);
                        CREATE INDEX IF NOT EXISTS tgmsg_message_id_idx
                            ON telegram_messages (message_id);
                    """,
                    reverse_sql="DROP TABLE IF EXISTS telegram_messages;",
                ),
            ],
        ),
    ]
