"""
Reports part of `clone_tenant_config` (see apps.tenants.config_clone): PnL /
cash-flow sources, rules and templates. The accounting start month and opening
balance are the source branch's — they are copied but flagged for review.
"""

from __future__ import annotations

from apps.modules.reports.models import TenantReportSettings

_FIELDS = ("pnl_source", "pnl_config", "cashflow_source", "cashflow_config", "default_template", "allowed_templates")


def clone(ctx) -> None:
    src = TenantReportSettings.objects.filter(tenant=ctx.source).first()
    if src is None or TenantReportSettings.objects.filter(tenant=ctx.target).exists():
        return
    TenantReportSettings.objects.create(tenant=ctx.target, **{name: getattr(src, name) for name in _FIELDS})
    ctx.change("Отчёты: настройки скопированы.")
    start = (src.pnl_config or {}).get("start_month")
    if start:
        ctx.warn(f"Отчёты: месяц начала учёта {start} и начальный остаток взяты у источника — укажите свои.")
