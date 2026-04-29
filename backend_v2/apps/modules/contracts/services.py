"""Contract display helpers (avoid importing serializers from models)."""

from django.utils import timezone

from apps.modules.contracts.models import Contract


def effective_contract_display(contract: Contract) -> tuple[str, bool]:
    """
    Returns (display_status, is_expired_flag).
    display_status: accepted | refused | expired
    """
    if contract.contract_status == Contract.STATUS_REFUSED:
        return "refused", False
    today = timezone.localdate()
    if (
        contract.contract_status == Contract.STATUS_ACCEPTED
        and contract.date_to
        and contract.date_to < today
    ):
        return "expired", True
    return "accepted", False


def tenant_has_contracts_module(*, tenant) -> bool:
    from apps.tenants.models import TenantModuleConfig

    if not tenant:
        return False
    return TenantModuleConfig.objects.filter(
        tenant=tenant, module_key="contracts", is_enabled=True
    ).exists()
