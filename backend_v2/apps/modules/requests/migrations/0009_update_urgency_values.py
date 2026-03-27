from django.db import migrations, models


def forwards(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    Request.objects.filter(urgency="Низкая").update(urgency="Низко")
    Request.objects.filter(urgency="Обычная").update(urgency="Обычно")
    Request.objects.filter(urgency="Высокая").update(urgency="Срочно")


def backwards(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    Request.objects.filter(urgency="Низко").update(urgency="Низкая")
    Request.objects.filter(urgency="Обычно").update(urgency="Обычная")
    Request.objects.filter(urgency="Срочно").update(urgency="Высокая")


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0008_created_by_non_null"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="request",
            name="urgency",
            field=models.CharField(
                choices=[("Низко", "Низко"), ("Обычно", "Обычно"), ("Срочно", "Срочно")],
                default="Обычно",
                max_length=50,
            ),
        ),
    ]

