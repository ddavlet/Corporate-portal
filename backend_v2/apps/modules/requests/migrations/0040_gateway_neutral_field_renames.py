from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0039_request_contract_ref_form_contracts_required"),
    ]

    operations = [
        migrations.RenameField(
            model_name="approval",
            old_name="approver_tg_id",
            new_name="approver_recipient_id",
        ),
        migrations.RenameField(
            model_name="approval",
            old_name="approver_tg_from_id",
            new_name="approver_external_user_id",
        ),
        migrations.RenameField(
            model_name="approval",
            old_name="message_id",
            new_name="gateway_message_id",
        ),
        # UserRequestApproval is unmanaged (`managed=False`) and shares `approvals` via AlterModelTable;
        # its migration state has never tracked tg/message mirror fields — renames run via Approval only.
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_bridge_dispatch_url",
            new_name="messaging_gateway_dispatch_url",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_send_action",
            new_name="messaging_gateway_send_action",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_edit_action",
            new_name="messaging_gateway_edit_action",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_draft_notification_action",
            new_name="messaging_gateway_draft_action",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_bridge_token",
            new_name="messaging_gateway_token",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_message_template",
            new_name="messaging_gateway_message_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_header_new_template",
            new_name="messaging_gateway_header_new_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_header_step_approved_template",
            new_name="messaging_gateway_header_step_approved_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_header_fully_approved_template",
            new_name="messaging_gateway_header_fully_approved_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_header_closed_template",
            new_name="messaging_gateway_header_closed_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_header_rejected_template",
            new_name="messaging_gateway_header_rejected_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_subheader_payment_responsible_template",
            new_name="messaging_gateway_subheader_payment_responsible_template",
        ),
        migrations.RenameField(
            model_name="requestapprovalconfig",
            old_name="telegram_approvals_subheader_rejected_by_template",
            new_name="messaging_gateway_subheader_rejected_by_template",
        ),
        migrations.RemoveField(
            model_name="requestapprovalconfig",
            name="n8n_integration_token",
        ),
    ]
