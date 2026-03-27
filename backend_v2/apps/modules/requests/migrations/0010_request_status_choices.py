from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0009_update_urgency_values"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "DRAFT"),
                    ("1-5", "1-5"),
                    ("APPROVED", "APPROVED"),
                    ("PAYED", "PAYED"),
                    ("REJECTED", "REJECTED"),
                ],
                default="DRAFT",
                max_length=50,
            ),
        ),
    ]
