from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0008_task_model_cleanup"),
        ("telegram_approvals", "0002_telegram_message"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="task",
                    name="telegram_message",
                    field=models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="task",
                        to="telegram_approvals.telegrammessage",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE tasks
                            ADD COLUMN IF NOT EXISTS telegram_message_id bigint NULL
                                REFERENCES telegram_messages(id)
                                ON DELETE SET NULL
                                DEFERRABLE INITIALLY DEFERRED;
                        CREATE UNIQUE INDEX IF NOT EXISTS tasks_telegram_message_id_key
                            ON tasks (telegram_message_id)
                            WHERE telegram_message_id IS NOT NULL;
                    """,
                    reverse_sql="ALTER TABLE tasks DROP COLUMN IF EXISTS telegram_message_id;",
                ),
            ],
        ),
    ]
