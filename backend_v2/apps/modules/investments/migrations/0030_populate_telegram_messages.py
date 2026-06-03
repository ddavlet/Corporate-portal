# Data migration: copy existing investment approval gateway_message_id → TelegramMessage rows
# before the column removal migration.

from django.db import migrations, connection
from django.utils import timezone


def _column_exists(table, column):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        """, [table, column])
        return cursor.fetchone()[0] > 0


def populate_telegram_messages_for_investments(apps, schema_editor):
    TelegramMessage = apps.get_model("telegram_approvals", "TelegramMessage")

    if _column_exists("investment_return_approvals", "gateway_message_id"):
        InvestReturnApproval = apps.get_model("investments", "InvestmentReturnApproval")
        created_ir = 0
        for approval in (
            InvestReturnApproval.objects
            .filter(
                gateway_message_id__isnull=False,
                telegram_message__isnull=True,
            )
            .iterator(chunk_size=200)
        ):
            # Match on recipient too (message_id is unique per chat, not per tenant).
            existing = TelegramMessage.objects.filter(
                message_id=approval.gateway_message_id,
                tenant=approval.tenant,
                recipient_id=str(approval.approver_recipient_id or ""),
            ).first()
            if existing:
                approval.telegram_message = existing
                approval.save(update_fields=["telegram_message"])
            else:
                tm = TelegramMessage.objects.create(
                    tenant=approval.tenant,
                    recipient_id=str(approval.approver_recipient_id or ""),
                    external_user_id=approval.approver_external_user_id,
                    message_id=approval.gateway_message_id,
                    sent_at=approval.message_sent_at or timezone.now(),
                )
                approval.telegram_message = tm
                approval.save(update_fields=["telegram_message"])
                created_ir += 1
        print(f"  InvestmentReturnApproval: created {created_ir} TelegramMessage rows")
    else:
        print("  InvestmentReturnApproval: gateway_message_id already removed, skipping")

    if _column_exists("project_investment_approvals", "gateway_message_id"):
        ProjectInvestmentApproval = apps.get_model("investments", "ProjectInvestmentApproval")
        created_pi = 0
        for approval in (
            ProjectInvestmentApproval.objects
            .filter(
                gateway_message_id__isnull=False,
                telegram_message__isnull=True,
            )
            .iterator(chunk_size=200)
        ):
            # Match on recipient too (message_id is unique per chat, not per tenant).
            existing = TelegramMessage.objects.filter(
                message_id=approval.gateway_message_id,
                tenant=approval.tenant,
                recipient_id=str(approval.approver_recipient_id or ""),
            ).first()
            if existing:
                approval.telegram_message = existing
                approval.save(update_fields=["telegram_message"])
            else:
                tm = TelegramMessage.objects.create(
                    tenant=approval.tenant,
                    recipient_id=str(approval.approver_recipient_id or ""),
                    external_user_id=approval.approver_external_user_id,
                    message_id=approval.gateway_message_id,
                    sent_at=approval.message_sent_at or timezone.now(),
                )
                approval.telegram_message = tm
                approval.save(update_fields=["telegram_message"])
                created_pi += 1
        print(f"  ProjectInvestmentApproval: created {created_pi} TelegramMessage rows")
    else:
        print("  ProjectInvestmentApproval: gateway_message_id already removed, skipping")


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
