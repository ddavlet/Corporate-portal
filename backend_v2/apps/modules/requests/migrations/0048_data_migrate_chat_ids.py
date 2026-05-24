from django.db import migrations


def migrate_request_chat_ids(apps, schema_editor):
    RequestApprovalStepConfig = apps.get_model('requests', 'RequestApprovalStepConfig')
    RequestApprovalPurposeExceptionStepConfig = apps.get_model('requests', 'RequestApprovalPurposeExceptionStepConfig')
    TenantTelegramChat = apps.get_model('telegram_approvals', 'TenantTelegramChat')

    # RequestApprovalStepConfig: path to tenant via payment_type_config.config.tenant
    for step in RequestApprovalStepConfig.objects.filter(payment_chat_id__isnull=False).select_related(
        'payment_type_config__config__tenant'
    ):
        tenant = step.payment_type_config.config.tenant
        chat, _ = TenantTelegramChat.objects.get_or_create(
            tenant=tenant,
            chat_id=str(step.payment_chat_id),
            defaults={'name': f'Чат {step.payment_chat_id}'},
        )
        step.telegram_chat = chat
        step.save(update_fields=['telegram_chat'])

    # RequestApprovalPurposeExceptionStepConfig: path via exception_config.payment_type_config.config.tenant
    for step in RequestApprovalPurposeExceptionStepConfig.objects.filter(payment_chat_id__isnull=False).select_related(
        'exception_config__payment_type_config__config__tenant'
    ):
        tenant = step.exception_config.payment_type_config.config.tenant
        chat, _ = TenantTelegramChat.objects.get_or_create(
            tenant=tenant,
            chat_id=str(step.payment_chat_id),
            defaults={'name': f'Чат {step.payment_chat_id}'},
        )
        step.telegram_chat = chat
        step.save(update_fields=['telegram_chat'])


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0047_add_telegram_chat_fk'),
    ]

    operations = [
        migrations.RunPython(migrate_request_chat_ids, migrations.RunPython.noop),
    ]
