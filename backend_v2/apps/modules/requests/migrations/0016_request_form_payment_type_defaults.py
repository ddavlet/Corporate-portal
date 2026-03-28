import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0002_enable_vendors_for_requests_tenants"),
        ("requests", "0015_move_vendor_to_vendors_app"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_title",
            field=models.CharField(default="", max_length=200),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_description",
            field=models.TextField(default=""),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_amount",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_currency",
            field=models.CharField(default="UZS", max_length=10),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_urgency",
            field=models.CharField(default="Обычно", max_length=50),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_billing_days_offset",
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_payment_purpose",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="default_vendor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="request_form_default_for_payment_types",
                to="vendors.vendor",
            ),
        ),
    ]
