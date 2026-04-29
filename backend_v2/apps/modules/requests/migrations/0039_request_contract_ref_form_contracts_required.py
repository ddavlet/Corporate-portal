import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0001_initial"),
        ("requests", "0038_requestapprovalpurposeexceptionconfig_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestformpaymenttypeconfig",
            name="contracts_required",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="request",
            name="contract_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="requests",
                to="contracts.contract",
            ),
        ),
        migrations.AddField(
            model_name="autorequesttemplate",
            name="contract_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="auto_request_templates",
                to="contracts.contract",
            ),
        ),
    ]
