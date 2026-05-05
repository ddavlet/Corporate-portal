from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0010_remove_investmentreturnapproval_invrapp_recipient_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="investmentapprovalconfigstep",
            name="payment_chat_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="investmentapprovalconfigstep",
            name="step_type",
            field=models.CharField(
                choices=[("serial", "serial"), ("confirmation", "confirmation")],
                default="serial",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="investmentreturnapproval",
            name="step_type",
            field=models.CharField(
                choices=[("serial", "serial"), ("confirmation", "confirmation")],
                default="serial",
                max_length=16,
            ),
        ),
    ]
