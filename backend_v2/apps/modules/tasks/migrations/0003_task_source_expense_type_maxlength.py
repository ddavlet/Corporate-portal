from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0002_tasksconfig"),
    ]

    operations = [
        migrations.AlterField(
            model_name="task",
            name="source_expense_type",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
