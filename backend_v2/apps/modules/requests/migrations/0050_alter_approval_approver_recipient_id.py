from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0049_remove_payment_chat_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approval",
            name="approver_recipient_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
