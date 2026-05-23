from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0022_investnotificationconfig_notify_hour'),
    ]

    operations = [
        migrations.AddField(
            model_name='investnotificationconfig',
            name='chat_id',
            field=models.CharField(
                blank=True,
                help_text='Telegram group chat ID for notifications. Overrides responsible_user\'s personal chat if set.',
                max_length=50,
                null=True,
            ),
        ),
    ]
