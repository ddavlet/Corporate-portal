from apps.modules.n8n_integration.views import N8nPayrollLineBatchUpsertView, N8nPayrollLineUpsertView
from apps.modules.payroll.models import PayrollDocument
from apps.modules.payroll.services import maybe_create_linked_request


def _maybe_link_request_for_doc_id(request, raw_doc_id) -> None:
    tenant = getattr(request, "tenant", None)
    if tenant is None or not tenant.create_payment_request_on_payroll_accrual:
        return
    doc_id = str(raw_doc_id or "").strip()
    if not doc_id:
        return
    document = PayrollDocument.objects.filter(tenant=tenant, doc_id=doc_id).first()
    if document is not None:
        maybe_create_linked_request(document, actor_user=None)


class PayrollLineUpsertWithLinkedRequestView(N8nPayrollLineUpsertView):
    """
    Identical to N8nPayrollLineUpsertView (parent's post() is called verbatim,
    unmodified). After a successful single-line upsert, optionally creates the
    tenant's linked payment Request for the affected document — only when
    Tenant.create_payment_request_on_payroll_accrual is enabled. No-op otherwise.
    """

    def post(self, request):
        response = super().post(request)
        if response.status_code < 300:
            _maybe_link_request_for_doc_id(request, request.data.get("doc_id"))
        return response


class PayrollLineBatchUpsertWithLinkedRequestView(N8nPayrollLineBatchUpsertView):
    """
    Identical batch behaviour to N8nPayrollLineBatchUpsertView — single_view_class
    stays the plain N8nPayrollLineUpsertView (not the hooked variant above), so the
    per-line hook never fires mid-batch and never sees a partial line total. After
    the whole batch commits, runs the hook once per distinct doc_id present in the
    payload — safe because a full accrual document always arrives in one request
    (confirmed: it is never split across multiple batch calls).
    """

    def post(self, request):
        response = super().post(request)
        if response.status_code < 300 and isinstance(request.data, list):
            tenant = getattr(request, "tenant", None)
            if tenant is not None and tenant.create_payment_request_on_payroll_accrual:
                seen_doc_ids: set[str] = set()
                for item in request.data:
                    if not isinstance(item, dict):
                        continue
                    doc_id = str(item.get("doc_id") or "").strip()
                    if doc_id and doc_id not in seen_doc_ids:
                        seen_doc_ids.add(doc_id)
                        _maybe_link_request_for_doc_id(request, doc_id)
        return response
