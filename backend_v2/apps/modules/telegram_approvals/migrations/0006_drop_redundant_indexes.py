import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("telegram_approvals", "0005_telegram_event_log"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.AlterField(
            model_name="telegrammessage",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="telegram_messages",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="telegrammessagehistory",
            name="telegram_message",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="history",
                to="telegram_approvals.telegrammessage",
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="notifications",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="content_type",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                to="contenttypes.contenttype",
            ),
        ),
        migrations.AlterField(
            model_name="tenanttelegramchat",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="telegram_chats",
                to="tenants.tenant",
            ),
        ),
    ]
