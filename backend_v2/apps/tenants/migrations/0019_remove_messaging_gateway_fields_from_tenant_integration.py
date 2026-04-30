# Generated manually — messaging gateway URL/actions/templates are deployment-wide (settings).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0018_gateway_neutral_integration_fields"),
    ]

    operations = [
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_dispatch_url"),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_send_action"),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_edit_action"),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_draft_action"),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_message_template"),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_header_new_template"),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="messaging_gateway_header_step_approved_template",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="messaging_gateway_header_fully_approved_template",
        ),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_header_closed_template"),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="messaging_gateway_header_rejected_template",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="messaging_gateway_subheader_payment_responsible_template",
        ),
        migrations.RemoveField(
            model_name="tenantintegrationconfig",
            name="messaging_gateway_subheader_rejected_by_template",
        ),
        migrations.RemoveField(model_name="tenantintegrationconfig", name="messaging_gateway_token_enc"),
    ]
