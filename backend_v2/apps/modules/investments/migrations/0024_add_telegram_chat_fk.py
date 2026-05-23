import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0023_investnotificationconfig_chat_id'),
        ('telegram_approvals', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='investmentapprovalconfigstep',
            name='telegram_chat',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invest_approval_steps',
                to='telegram_approvals.tenanttelegramchat',
            ),
        ),
        migrations.AddField(
            model_name='investmentprojectapprovalconfigstep',
            name='telegram_chat',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invest_project_approval_steps',
                to='telegram_approvals.tenanttelegramchat',
            ),
        ),
        migrations.AddField(
            model_name='investnotificationconfig',
            name='telegram_chat',
            field=models.ForeignKey(
                blank=True,
                help_text='Telegram group chat for notifications. Overrides responsible_user\'s personal chat if set.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='invest_notification_configs',
                to='telegram_approvals.tenanttelegramchat',
            ),
        ),
    ]
