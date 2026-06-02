# Remove old stored gateway_message_id/message_sent/message_sent_at fields from
# InvestmentReturnApproval and ProjectInvestmentApproval.
# Data was already migrated to TelegramMessage by 0030_populate_telegram_messages.
# The old field names continue to work as read-only @property wrappers on the models.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0030_populate_telegram_messages"),
    ]

    operations = [
        # --- InvestmentReturnApproval ---
        migrations.RemoveIndex(
            model_name="investmentreturnapproval",
            name="invrapp_gateway_msg_idx",
        ),
        migrations.RemoveField(
            model_name="investmentreturnapproval",
            name="gateway_message_id",
        ),
        migrations.RemoveField(
            model_name="investmentreturnapproval",
            name="message_sent",
        ),
        migrations.RemoveField(
            model_name="investmentreturnapproval",
            name="message_sent_at",
        ),
        # --- ProjectInvestmentApproval ---
        migrations.RemoveIndex(
            model_name="projectinvestmentapproval",
            name="invpiapp_gateway_msg_idx",
        ),
        migrations.RemoveField(
            model_name="projectinvestmentapproval",
            name="gateway_message_id",
        ),
        migrations.RemoveField(
            model_name="projectinvestmentapproval",
            name="message_sent",
        ),
        migrations.RemoveField(
            model_name="projectinvestmentapproval",
            name="message_sent_at",
        ),
    ]
