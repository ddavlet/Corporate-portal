from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bank_expenses", "0012_alter_bankexpense_wallet_bankrevenue_wallet_required"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="bankexpense",
            name="account_name",
        ),
        migrations.RemoveField(
            model_name="bankexpense",
            name="inn",
        ),
        migrations.RemoveField(
            model_name="bankexpense",
            name="account_no",
        ),
        migrations.RemoveField(
            model_name="bankexpense",
            name="mfo",
        ),
    ]
