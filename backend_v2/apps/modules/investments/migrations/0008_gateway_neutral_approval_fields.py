from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0007_investment_approval_flow"),
    ]

    operations = [
        migrations.RenameField(
            model_name="investmentreturnapproval",
            old_name="approver_tg_id",
            new_name="approver_recipient_id",
        ),
        migrations.RenameField(
            model_name="investmentreturnapproval",
            old_name="approver_tg_from_id",
            new_name="approver_user_id",
        ),
        migrations.RenameField(
            model_name="investmentreturnapproval",
            old_name="message_id",
            new_name="gateway_message_id",
        ),
    ]
