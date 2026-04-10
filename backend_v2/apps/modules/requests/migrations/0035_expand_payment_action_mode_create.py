from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0034_remove_request_expense_ref_unique"),
    ]

    operations = [
        migrations.AlterField(
            model_name="requestapprovalstepconfig",
            name="payment_action_mode",
            field=models.CharField(
                choices=[("callback", "callback"), ("webapp", "webapp"), ("create", "create")],
                default="callback",
                max_length=12,
            ),
        ),
    ]
