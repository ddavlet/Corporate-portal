from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cashier", "0009_cashrevenue_import_fields"),
    ]

    operations = [
        migrations.RemoveField(model_name="cashrevenue", name="title"),
        migrations.RemoveField(model_name="cashrevenue", name="amount"),
        migrations.RemoveField(model_name="cashrevenue", name="category"),
        migrations.RemoveField(model_name="cashrevenue", name="received_from"),
        migrations.RemoveField(model_name="cashrevenue", name="payment_method"),
        migrations.RemoveField(model_name="cashrevenue", name="reference_no"),
        migrations.RemoveField(model_name="cashrevenue", name="status"),
        migrations.RemoveField(model_name="cashrevenue", name="tags"),
        migrations.RemoveField(model_name="cashrevenue", name="note"),
    ]
