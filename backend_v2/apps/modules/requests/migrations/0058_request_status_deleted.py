from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0057_userrequestapproval_telegram_message"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "DRAFT"),
                    ("1", "1"),
                    ("2", "2"),
                    ("3", "3"),
                    ("4", "4"),
                    ("5", "5"),
                    ("APPROVED", "APPROVED"),
                    ("PAYED", "PAYED"),
                    ("REJECTED", "REJECTED"),
                    ("DELETED", "DELETED"),
                ],
                default="DRAFT",
                max_length=50,
            ),
        ),
    ]
