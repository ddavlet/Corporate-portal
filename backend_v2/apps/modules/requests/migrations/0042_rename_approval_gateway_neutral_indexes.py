from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0041_remove_messaging_gateway_fields_from_request_approval_config"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="approval",
            new_name="approvals_appr_rcpt_idx",
            old_name="approvals_approver_tg_id_idx",
        ),
        migrations.RenameIndex(
            model_name="approval",
            new_name="approvals_ext_uid_idx",
            old_name="approvals_tg_from_idx",
        ),
    ]
