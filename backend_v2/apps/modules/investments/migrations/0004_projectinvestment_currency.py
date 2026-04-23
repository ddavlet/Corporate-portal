from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0003_invest_models_timestamps"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectinvestment",
            name="currency",
            field=models.CharField(default="USD", max_length=3),
        ),
    ]
