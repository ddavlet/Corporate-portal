from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0022_requestformpaymenttypeconfig_default_company_payer"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestapprovalstepconfig",
            name="payment_action_mode",
            field=models.CharField(
                choices=[("callback", "callback"), ("webapp", "webapp")],
                default="callback",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="requestapprovalstepconfig",
            name="payment_webapp_url",
            field=models.TextField(blank=True, default=""),
        ),
    ]
