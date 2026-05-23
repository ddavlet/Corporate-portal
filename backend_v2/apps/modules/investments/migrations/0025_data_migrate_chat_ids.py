from django.db import migrations


def migrate_invest_chat_ids(apps, schema_editor):
    InvestmentApprovalConfigStep = apps.get_model('investments', 'InvestmentApprovalConfigStep')
    InvestmentProjectApprovalConfigStep = apps.get_model('investments', 'InvestmentProjectApprovalConfigStep')
    InvestNotificationConfig = apps.get_model('investments', 'InvestNotificationConfig')
    TenantTelegramChat = apps.get_model('telegram_approvals', 'TenantTelegramChat')

    # InvestmentApprovalConfigStep: path to tenant via config.tenant
    for step in InvestmentApprovalConfigStep.objects.filter(payment_chat_id__isnull=False).select_related('config__tenant'):
        tenant = step.config.tenant
        chat, _ = TenantTelegramChat.objects.get_or_create(
            tenant=tenant,
            chat_id=str(step.payment_chat_id),
            defaults={'name': f'Чат {step.payment_chat_id}'},
        )
        step.telegram_chat = chat
        step.save(update_fields=['telegram_chat'])

    # InvestmentProjectApprovalConfigStep: path to tenant via config.tenant
    for step in InvestmentProjectApprovalConfigStep.objects.filter(payment_chat_id__isnull=False).select_related('config__tenant'):
        tenant = step.config.tenant
        chat, _ = TenantTelegramChat.objects.get_or_create(
            tenant=tenant,
            chat_id=str(step.payment_chat_id),
            defaults={'name': f'Чат {step.payment_chat_id}'},
        )
        step.telegram_chat = chat
        step.save(update_fields=['telegram_chat'])

    # InvestNotificationConfig: has direct tenant FK, and chat_id CharField we added
    for cfg in InvestNotificationConfig.objects.filter(chat_id__isnull=False).exclude(chat_id='').select_related('tenant'):
        chat, _ = TenantTelegramChat.objects.get_or_create(
            tenant=cfg.tenant,
            chat_id=cfg.chat_id,
            defaults={'name': f'Чат {cfg.chat_id}'},
        )
        cfg.telegram_chat = chat
        cfg.save(update_fields=['telegram_chat'])


class Migration(migrations.Migration):

    dependencies = [
        ('investments', '0024_add_telegram_chat_fk'),
    ]

    operations = [
        migrations.RunPython(migrate_invest_chat_ids, migrations.RunPython.noop),
    ]
