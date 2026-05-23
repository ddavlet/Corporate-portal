from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0025_data_migrate_chat_ids'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='investmentapprovalconfigstep',
            name='payment_chat_id',
        ),
        migrations.RemoveField(
            model_name='investmentprojectapprovalconfigstep',
            name='payment_chat_id',
        ),
        migrations.RemoveField(
            model_name='investnotificationconfig',
            name='chat_id',
        ),
    ]
