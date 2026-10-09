"""Which requests count toward a budget — shared by the API, the serializer and MCP tools."""

from apps.modules.requests.models import Request, RequestPaymentPurposeConfig


def budget_spend_requests(budget, start, end):
    """APPROVED and PAYED requests in the budget's currency with billing_date in [start, end)."""
    qs = Request.objects.filter(
        tenant_id=budget.tenant_id,
        currency=budget.currency,
        status__in=[Request.STATUS_APPROVED, Request.STATUS_PAYED],
        billing_date__gte=start,
        billing_date__lt=end,
    )
    if budget.payment_purpose:
        return qs.filter(payment_purpose=budget.payment_purpose)
    return qs.filter(category=budget.category.name)


def list_payment_purposes(tenant_id: int) -> list[dict]:
    """Purposes to budget by: active ones from the request form config plus any used on requests.

    Each item carries the category it belongs to in the form config ("" when unknown).
    """
    categories: dict[str, str] = {}
    for name, category in (
        RequestPaymentPurposeConfig.objects.filter(
            payment_type_config__config__tenant_id=tenant_id, is_active=True
        ).values_list("name", "category")
    ):
        name = (name or "").strip()
        if name and not categories.get(name):
            categories[name] = (category or "").strip()
    used = (
        Request.objects.filter(tenant_id=tenant_id)
        .exclude(payment_purpose="")
        .values_list("payment_purpose", flat=True)
        .distinct()
    )
    for name in used:
        name = (name or "").strip()
        if name:
            categories.setdefault(name, "")
    return [{"name": n, "category": categories[n]} for n in sorted(categories, key=str.lower)]

