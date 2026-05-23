from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0048_data_migrate_chat_ids'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='requestapprovalstepconfig',
            name='payment_chat_id',
        ),
        migrations.RemoveField(
            model_name='requestapprovalpurposeexceptionstepconfig',
            name='payment_chat_id',
        ),
    ]
