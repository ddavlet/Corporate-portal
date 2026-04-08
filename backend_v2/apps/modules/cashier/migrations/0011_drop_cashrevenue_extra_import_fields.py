from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cashier", "0010_drop_cashrevenue_legacy_fields"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="cashrevenue",
            name="cash_type",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="contract",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="direction",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="employee",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="organization",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="revenue_date",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="source_year",
        ),
        migrations.RemoveField(
            model_name="cashrevenue",
            name="unit",
        ),
    ]
