import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0046_request_tenant_payment_purpose_idx'),
        ('telegram_approvals', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='requestapprovalstepconfig',
            name='telegram_chat',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='request_approval_steps',
                to='telegram_approvals.tenanttelegramchat',
            ),
        ),
        migrations.AddField(
            model_name='requestapprovalpurposeexceptionstepconfig',
            name='telegram_chat',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='request_purpose_exception_steps',
                to='telegram_approvals.tenanttelegramchat',
            ),
        ),
    ]
