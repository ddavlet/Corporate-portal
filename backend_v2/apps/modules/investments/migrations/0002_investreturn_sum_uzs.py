from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="investreturn",
            name="sum_uzs",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
        ),
    ]
