# Add telegram_message FK to UserRequestApproval (managed=False model).
# The column already exists on the 'approvals' table from migration 0054.
# This migration uses SeparateDatabaseAndState to register the field in Django's
# model state without running a database operation.
#
# NOTE: gateway_message_id / message_sent / message_sent_at are intentionally NOT
# removed here. UserRequestApproval's migration state has never tracked those
# "mirror" fields (see the comment in 0040_gateway_neutral_field_renames) — they
# live only on the live managed=False model as @property accessors. RemoveField on
# them would raise FieldDoesNotExist and break `migrate`.

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
