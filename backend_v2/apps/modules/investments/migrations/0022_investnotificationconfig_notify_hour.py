import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0021_investnotificationconfig_overdue_notify_every_days_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='investnotificationconfig',
            name='notify_hour',
            field=models.PositiveSmallIntegerField(
                default=9,
                help_text='Hour of day (0–23, Asia/Tashkent) when notifications are dispatched.',
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(23),
                ],
            ),
        ),
    ]
