# Hand-written: snapshot of request amount/currency on the transfer target

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cash_desk", "0002_seed_cash_groups"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashregistertransfertarget",
            name="source_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="cashregistertransfertarget",
            name="source_currency",
            field=models.CharField(blank=True, max_length=3, null=True),
        ),
    ]
