from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0008_gateway_neutral_approval_fields"),
    ]

    operations = [
        migrations.RenameIndex(
            model_name="investmentreturnapproval",
            new_name="invrapp_recipient_idx",
            old_name="invrapp_tg_id_idx",
        ),
        migrations.RenameIndex(
            model_name="investmentreturnapproval",
            new_name="invrapp_gateway_msg_idx",
            old_name="invrapp_msg_id_idx",
        ),
    ]
