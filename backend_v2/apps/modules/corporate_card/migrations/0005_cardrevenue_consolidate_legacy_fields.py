from django.db import migrations

LEGACY_PAYLOAD_KEYS = (
    "direction",
    "organization",
    "unit",
    "employee",
    "cash_type",
    "account",
    "source_year",
)


def _consolidate_card_revenue_legacy_fields(apps, schema_editor):
    CardRevenue = apps.get_model("corporate_card", "CardRevenue")
    for row in CardRevenue.objects.iterator(chunk_size=500):
        updates = {}
        payload = dict(row.payload or {})
        payload_changed = False

        if not str(row.comment or "").strip() and str(row.note or "").strip():
            updates["comment"] = row.note

        if row.total_sum == 0 and row.amount:
            updates["total_sum"] = row.amount

        if not str(row.operation or "").strip() and str(row.title or "").strip():
            updates["operation"] = row.title

        for key in LEGACY_PAYLOAD_KEYS:
            col_val = getattr(row, key, None)
            if col_val in (None, "", 0):
                continue
            if payload.get(key) in (None, "", 0):
                payload[key] = col_val
                payload_changed = True

        if str(row.title or "").strip() and not payload.get("title"):
            payload["title"] = row.title
            payload_changed = True
        if str(row.note or "").strip() and not payload.get("note"):
            payload["note"] = row.note
            payload_changed = True

        if payload_changed:
            updates["payload"] = payload

        if updates:
            CardRevenue.objects.filter(pk=row.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_card", "0004_alter_cardexpense_wallet_cardrevenue_wallet_required"),
    ]

    operations = [
        migrations.RunPython(
            _consolidate_card_revenue_legacy_fields,
            migrations.RunPython.noop,
        ),
    ]
