from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0004_created_by_fields"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="bankexpense",
            options={},
        ),
        migrations.AlterModelOptions(
            name="bankrevenue",
            options={},
        ),
    ]

