from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0026_approval_message_sent_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="autorequesttemplate",
            name="billing_month_mode",
            field=models.CharField(
                choices=[
                    ("previous", "Предыдущий месяц"),
                    ("current", "Этот месяц"),
                    ("next", "Следующий месяц"),
                ],
                default="current",
                max_length=20,
            ),
        ),
    ]
