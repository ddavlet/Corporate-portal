import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0019_alter_investmentapprovalconfigstep_step_type_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='InvestNotificationConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('days_before', models.PositiveIntegerField(default=3)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('responsible_user', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='invest_notification_configs', to=settings.AUTH_USER_MODEL)),
                ('tenant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='invest_notification_config', to='tenants.tenant')),
            ],
            options={
                'db_table': 'invest_notification_config',
            },
        ),
        migrations.CreateModel(
            name='InvestPayoutNotificationLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sent_at', models.DateTimeField(auto_now_add=True)),
                ('sent_date', models.DateField()),
                ('recipient_user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invest_payout_notification_logs', to=settings.AUTH_USER_MODEL)),
                ('schedule', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notification_logs', to='investments.investpayoutschedule')),
            ],
            options={
                'db_table': 'invest_payout_notification_logs',
            },
        ),
        migrations.AddConstraint(
            model_name='investpayoutnotificationlog',
            constraint=models.UniqueConstraint(fields=['schedule', 'recipient_user', 'sent_date'], name='invnotlog_sched_user_date_uniq'),
        ),
        migrations.AddIndex(
            model_name='investpayoutnotificationlog',
            index=models.Index(fields=['schedule', 'sent_date'], name='invnotlog_sched_date_idx'),
        ),
    ]
