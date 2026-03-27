from django.db import migrations, models


def forwards(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    Request.objects.filter(status="1-5").update(status="1")


def backwards(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    Request.objects.filter(status="1").update(status="1-5")


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0012_create_approvals_table"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
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
                ],
                default="DRAFT",
                max_length=50,
            ),
        ),
    ]
