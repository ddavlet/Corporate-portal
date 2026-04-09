from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0011_drop_cashrevenue_extra_import_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="cashrevenue",
            name="account",
        ),
    ]
