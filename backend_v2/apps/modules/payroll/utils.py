from apps.modules.payroll.constants import MODULE_KEY
from apps.modules.requests.models import Request
from apps.tenants.models import TenantModuleConfig


def tenant_has_payroll_module_enabled(tenant) -> bool:
    if not tenant:
        return False
    return TenantModuleConfig.objects.filter(tenant=tenant, module_key=MODULE_KEY, is_enabled=True).exists()


def is_payroll_payment_request(request_obj: Request, tenant) -> bool:
    if not request_obj or not tenant:
        return False
    if request_obj.payment_type != Request.PAYMENT_TYPE_PAYROLL:
        return False
    return tenant_has_payroll_module_enabled(tenant)
