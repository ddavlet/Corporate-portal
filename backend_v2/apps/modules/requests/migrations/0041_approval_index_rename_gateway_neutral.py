from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0040_gateway_neutral_field_renames"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="approval",
            new_name="approvals_appr_rcpt_idx",
            old_name="approvals_approver_recipient_idx",
        ),
        migrations.RenameIndex(
            model_name="approval",
            new_name="approvals_ext_uid_idx",
            old_name="approvals_user_id_idx",
        ),
    ]
