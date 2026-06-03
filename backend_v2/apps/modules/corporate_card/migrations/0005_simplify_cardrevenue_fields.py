from decimal import Decimal

from django.db import migrations, models


LEGACY_TEXT_FIELDS = (
    "direction",
    "organization",
    "unit",
    "employee",
    "cash_type",
    "operation",
    "account",
    "counterparty",
)


def _merge_legacy_into_payload(apps, schema_editor):
    CardRevenue = apps.get_model("corporate_card", "CardRevenue")
    for row in CardRevenue.objects.all().iterator():
        payload = dict(row.payload or {})
        legacy = dict(payload.get("legacy_import") or {})

        for name in LEGACY_TEXT_FIELDS:
            value = getattr(row, name, "") or ""
            if value and name not in legacy:
                legacy[name] = value

        if row.revenue_date:
            legacy.setdefault("revenue_date", row.revenue_date.isoformat())
        if row.source_year is not None:
            legacy.setdefault("source_year", row.source_year)
        if row.bank_expense_id:
            legacy.setdefault("bank_expense_id", row.bank_expense_id)

        amount = row.amount or Decimal("0")
        total_sum = row.total_sum or Decimal("0")
        if amount == 0 and total_sum != 0:
            amount = total_sum
        elif total_sum != 0 and total_sum != amount:
            legacy.setdefault("total_sum", str(total_sum))

        note = (row.note or "").strip()
        comment = (row.comment or "").strip()
        if comment and not note:
            note = comment
        elif comment and comment != note:
            legacy.setdefault("comment", comment)

        updates = {"amount": amount, "note": note}
        if legacy:
            payload["legacy_import"] = legacy
            updates["payload"] = payload

        CardRevenue.objects.filter(pk=row.pk).update(**updates)


class Migration(migrations.Migration):
    dependencies = [
        ("corporate_card", "0004_alter_cardexpense_wallet_cardrevenue_wallet_required"),
    ]

    operations = [
        migrations.RunPython(_merge_legacy_into_payload, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="cardrevenue",
            name="corp_card_rev_bank_id_idx",
        ),
        migrations.RemoveField(model_name="cardrevenue", name="revenue_date"),
        migrations.RemoveField(model_name="cardrevenue", name="direction"),
        migrations.RemoveField(model_name="cardrevenue", name="organization"),
        migrations.RemoveField(model_name="cardrevenue", name="unit"),
        migrations.RemoveField(model_name="cardrevenue", name="employee"),
        migrations.RemoveField(model_name="cardrevenue", name="cash_type"),
        migrations.RemoveField(model_name="cardrevenue", name="operation"),
        migrations.RemoveField(model_name="cardrevenue", name="account"),
        migrations.RemoveField(model_name="cardrevenue", name="counterparty"),
        migrations.RemoveField(model_name="cardrevenue", name="total_sum"),
        migrations.RemoveField(model_name="cardrevenue", name="comment"),
        migrations.RemoveField(model_name="cardrevenue", name="source_year"),
        migrations.RemoveField(model_name="cardrevenue", name="bank_expense_id"),
        migrations.AlterField(
            model_name="cardrevenue",
            name="external_id",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
