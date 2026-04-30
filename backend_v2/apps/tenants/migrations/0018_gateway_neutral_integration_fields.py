from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0017_tenantintegrationconfig_telegram_oidc_fields"),
    ]

    operations = [
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_bridge_dispatch_url",
            new_name="messaging_gateway_dispatch_url",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_send_action",
            new_name="messaging_gateway_send_action",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_edit_action",
            new_name="messaging_gateway_edit_action",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_draft_notification_action",
            new_name="messaging_gateway_draft_action",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_message_template",
            new_name="messaging_gateway_message_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_header_new_template",
            new_name="messaging_gateway_header_new_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_header_step_approved_template",
            new_name="messaging_gateway_header_step_approved_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_header_fully_approved_template",
            new_name="messaging_gateway_header_fully_approved_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_header_closed_template",
            new_name="messaging_gateway_header_closed_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_header_rejected_template",
            new_name="messaging_gateway_header_rejected_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_subheader_payment_responsible_template",
            new_name="messaging_gateway_subheader_payment_responsible_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_subheader_rejected_by_template",
            new_name="messaging_gateway_subheader_rejected_by_template",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="telegram_approvals_bridge_token_enc",
            new_name="messaging_gateway_token_enc",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="portal_feedback_telegram_chat_id",
            new_name="messaging_gateway_feedback_recipient_id",
        ),
        migrations.RenameField(
            model_name="tenantintegrationconfig",
            old_name="portal_feedback_telegram_action",
            new_name="messaging_gateway_feedback_action",
        ),
    ]
