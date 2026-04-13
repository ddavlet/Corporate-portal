from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0035_expand_payment_action_mode_create"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestapprovalpaymenttypeconfig",
            name="request_not_required_rules",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
