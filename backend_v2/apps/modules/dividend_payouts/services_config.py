"""Rule settings helpers: allowed payout types and options for the settings page."""

from __future__ import annotations

from apps.modules.investments.models import InvestmentFormConfig, InvestReturn
from apps.modules.requests.models import RequestPaymentPurposeConfig


def allowed_return_types(tenant) -> list[str]:
    """Whitelist from the investments form config; empty list means every type is allowed."""
    cfg = InvestmentFormConfig.objects.filter(tenant=tenant).first()
    if cfg is None:
        return []
    return list(cfg.allowed_return_types or [])


def options_payload(tenant) -> dict:
    allowed = allowed_return_types(tenant)
    return_types = [
        {"value": value, "label": label}
        for value, label in InvestReturn.ReturnType.choices
        if not allowed or value in allowed
    ]
    recipients = [{"value": value, "label": label} for value, label in InvestReturn.Recipient.choices]
    names = RequestPaymentPurposeConfig.objects.filter(
        payment_type_config__config__tenant=tenant, is_active=True
    ).values_list("name", flat=True)
    purposes = sorted({name.strip() for name in names if name and name.strip()})
    return {"return_types": return_types, "recipients": recipients, "payment_purposes": purposes}
