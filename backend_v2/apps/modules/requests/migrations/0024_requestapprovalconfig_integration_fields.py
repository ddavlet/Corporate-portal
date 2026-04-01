from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0023_requestapprovalstepconfig_payment_action_mode_and_webapp_url"),
    ]

    operations = [
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_bridge_dispatch_url",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_send_action",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_edit_action",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_bridge_token",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_message_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_header_new_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_header_step_approved_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_header_fully_approved_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_header_closed_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_header_rejected_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_subheader_payment_responsible_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="telegram_approvals_subheader_rejected_by_template",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="requestapprovalconfig",
            name="n8n_integration_token",
            field=models.TextField(blank=True, default=""),
        ),
    ]
