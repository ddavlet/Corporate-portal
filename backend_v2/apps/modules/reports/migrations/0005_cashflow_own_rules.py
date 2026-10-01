"""Cashflow gets its own calculation rules: a copy of today's PnL rules, so no number changes on deploy."""
from django.db import migrations

# Keys Cashflow must not copy: bank exclusions apply to PnL only, and Cashflow already has its own opening balance.
PNL_ONLY_KEYS = ("bank_exclude_purposes", "opening_balance")


def copy_pnl_rules_to_cashflow(apps, schema_editor):
    Settings = apps.get_model("reports", "TenantReportSettings")
    for row in Settings.objects.iterator():
        pnl = row.pnl_config if isinstance(row.pnl_config, dict) else {}
        cashflow = row.cashflow_config if isinstance(row.cashflow_config, dict) else {}
        if not pnl or "start_month" in cashflow:
            continue
        copied = {key: value for key, value in pnl.items() if key not in PNL_ONLY_KEYS}
        row.cashflow_config = {**copied, **cashflow}
        row.save(update_fields=["cashflow_config"])


def keep_only_cashflow_opening_balance(apps, schema_editor):
    Settings = apps.get_model("reports", "TenantReportSettings")
    for row in Settings.objects.iterator():
        cashflow = row.cashflow_config if isinstance(row.cashflow_config, dict) else {}
        kept = {"opening_balance": cashflow["opening_balance"]} if "opening_balance" in cashflow else {}
        if kept != cashflow:
            row.cashflow_config = kept
            row.save(update_fields=["cashflow_config"])


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0004_tenantreportsettings_report_templates"),
    ]

    operations = [
        migrations.RunPython(copy_pnl_rules_to_cashflow, keep_only_cashflow_opening_balance),
    ]
