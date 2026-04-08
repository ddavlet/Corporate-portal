from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cashier", "0008_alter_cashexpense_wallet_cashrevenue_wallet_required"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashrevenue",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="revenue_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="confirmed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="direction",
            field=models.CharField(blank=True, default="", max_length=25),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="organization",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="unit",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="employee",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="cash_type",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="operation",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="account",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="counterparty",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="contract",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="total_sum",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="comment",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="source_year",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
