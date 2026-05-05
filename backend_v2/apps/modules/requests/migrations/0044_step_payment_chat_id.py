from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0043_remove_approval_approvals_appr_rcpt_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestapprovalstepconfig",
            name="payment_chat_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="requestapprovalpurposeexceptionstepconfig",
            name="payment_chat_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
