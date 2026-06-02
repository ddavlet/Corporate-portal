# Remove old stored gateway_message_id/message_sent/message_sent_at fields from Approval.
# Data was already migrated to TelegramMessage by 0055_populate_telegram_messages.
# The old field names continue to work as read-only @property wrappers on the model.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0055_populate_telegram_messages"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="approval",
            name="gateway_message_id",
        ),
        migrations.RemoveField(
            model_name="approval",
            name="message_sent",
        ),
        migrations.RemoveField(
            model_name="approval",
            name="message_sent_at",
        ),
    ]
