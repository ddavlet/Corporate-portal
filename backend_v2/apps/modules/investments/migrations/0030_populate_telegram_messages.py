# Data migration: copy existing investment approval gateway_message_id → TelegramMessage rows
# before the column removal migration.

from django.db import migrations
from django.utils import timezone


def populate_telegram_messages_for_investments(apps, schema_editor):
    InvestReturnApproval = apps.get_model("investments", "InvestmentReturnApproval")
    ProjectInvestmentApproval = apps.get_model("investments", "ProjectInvestmentApproval")
    TelegramMessage = apps.get_model("telegram_approvals", "TelegramMessage")

    created_ir = 0
    for approval in InvestReturnApproval.objects.filter(
        gateway_message_id__isnull=False,
        telegram_message__isnull=True,
        approver_recipient_id__isnull=False,
    ):
        existing = TelegramMessage.objects.filter(
            message_id=approval.gateway_message_id,
            tenant=approval.tenant,
        ).first()
        if existing:
            approval.telegram_message = existing
            approval.save(update_fields=["telegram_message"])
        else:
            tm = TelegramMessage.objects.create(
                tenant=approval.tenant,
                recipient_id=str(approval.approver_recipient_id),
                external_user_id=approval.approver_external_user_id,
                message_id=approval.gateway_message_id,
                sent_at=approval.message_sent_at or timezone.now(),
            )
            approval.telegram_message = tm
            approval.save(update_fields=["telegram_message"])
            created_ir += 1

    created_pi = 0
    for approval in ProjectInvestmentApproval.objects.filter(
        gateway_message_id__isnull=False,
        telegram_message__isnull=True,
        approver_recipient_id__isnull=False,
    ):
        existing = TelegramMessage.objects.filter(
            message_id=approval.gateway_message_id,
            tenant=approval.tenant,
        ).first()
        if existing:
            approval.telegram_message = existing
            approval.save(update_fields=["telegram_message"])
        else:
            tm = TelegramMessage.objects.create(
                tenant=approval.tenant,
                recipient_id=str(approval.approver_recipient_id),
                external_user_id=approval.approver_external_user_id,
                message_id=approval.gateway_message_id,
                sent_at=approval.message_sent_at or timezone.now(),
            )
            approval.telegram_message = tm
            approval.save(update_fields=["telegram_message"])
            created_pi += 1

    print(f"  InvestmentReturnApproval: created {created_ir} TelegramMessage rows")
    print(f"  ProjectInvestmentApproval: created {created_pi} TelegramMessage rows")


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0029_add_telegram_message_fk"),
        ("telegram_approvals", "0003_notification"),
    ]

    operations = [
        migrations.RunPython(
            populate_telegram_messages_for_investments,
            migrations.RunPython.noop,
        ),
    ]
