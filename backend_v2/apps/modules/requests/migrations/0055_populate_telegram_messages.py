# Data migration: copy existing Approval.gateway_message_id → TelegramMessage rows
# before the column removal migration (applied separately to avoid race conditions).

from django.db import migrations, connection
from django.utils import timezone


def populate_telegram_messages_for_approvals(apps, schema_editor):
    # Guard: skip if gateway_message_id was already removed (re-run / prior partial deploy)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM information_schema.columns
            WHERE table_name = 'requests_approval'
              AND column_name = 'gateway_message_id'
        """)
        if cursor.fetchone()[0] == 0:
            return

    Approval = apps.get_model("requests", "Approval")
    TelegramMessage = apps.get_model("telegram_approvals", "TelegramMessage")

    approvals = (
        Approval.objects
        .filter(
            gateway_message_id__isnull=False,
            telegram_message__isnull=True,
            approver_recipient_id__isnull=False,
        )
        .select_related("request__tenant")
        .iterator(chunk_size=200)
    )

    created = 0
    linked = 0
    for approval in approvals:
        existing = TelegramMessage.objects.filter(
            message_id=approval.gateway_message_id,
            tenant=approval.request.tenant,
        ).first()
        if existing:
            approval.telegram_message = existing
            approval.save(update_fields=["telegram_message"])
            linked += 1
        else:
            tm = TelegramMessage.objects.create(
                tenant=approval.request.tenant,
                recipient_id=str(approval.approver_recipient_id),
                external_user_id=approval.approver_external_user_id,
                message_id=approval.gateway_message_id,
                sent_at=approval.message_sent_at or timezone.now(),
            )
            approval.telegram_message = tm
            approval.save(update_fields=["telegram_message"])
            created += 1

    print(f"  Created {created} TelegramMessage rows, linked {linked} existing")


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0054_approval_telegram_message"),
        ("telegram_approvals", "0003_notification"),
    ]

    operations = [
        migrations.RunPython(
            populate_telegram_messages_for_approvals,
            migrations.RunPython.noop,
        ),
    ]
