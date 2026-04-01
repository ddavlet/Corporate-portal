from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0008_tenantintegrationconfig_telegram_approvals_message_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_header_new_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_header_step_approved_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_header_fully_approved_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_header_closed_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_header_rejected_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_subheader_payment_responsible_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="tenantintegrationconfig",
            name="telegram_approvals_subheader_rejected_by_template",
            field=models.TextField(blank=True, default=""),
        ),
    ]
