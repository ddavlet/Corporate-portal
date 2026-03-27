from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("corporate_card", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardrevenue",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="revenue_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="confirmed",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="direction",
            field=models.CharField(blank=True, default="", max_length=25),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="organization",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="unit",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="employee",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="cash_type",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="operation",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="account",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="counterparty",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="total_sum",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="comment",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="cardrevenue",
            name="source_year",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]

