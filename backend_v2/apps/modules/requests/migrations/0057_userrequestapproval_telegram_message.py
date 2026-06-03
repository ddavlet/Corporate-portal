# Add telegram_message FK to UserRequestApproval (managed=False model).
# The column already exists on the 'approvals' table from migration 0054.
# This migration uses SeparateDatabaseAndState to register the field in Django's
# model state without running a database operation.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0056_remove_legacy_message_fields"),
        ("telegram_approvals", "0002_telegram_message"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="userrequestapproval",
                    name="telegram_message",
                    field=models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="user_request_approval",
                        to="telegram_approvals.telegrammessage",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
