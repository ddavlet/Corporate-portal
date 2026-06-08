import logging
import time
import uuid
from datetime import date, datetime
import requests
from requests.adapters import HTTPAdapter
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.payroll.models import PayrollLine
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.investments.approval_services import (
    create_approvals_for_invest_return,
    route_invest_return_approvals,
)
from apps.modules.investments.models import InvestCompany, InvestPayoutSchedule, InvestReturn, ProjectInvestment
from apps.modules.investments.serializers import InvestReturnSerializer
from apps.modules.notes.models import Note
from apps.modules.requests.models import Approval, Request
from apps.modules.requests.amortization import build_amortization_schedule_rows, is_request_amortized
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import _recalculate_request_status, route_request_approvals
from apps.modules.requests.serializers import PortalRequestSerializer
from apps.modules.requests.services import list_payment_purposes_by_payment_type
from apps.modules.vendors.models import Vendor
from apps.modules.n8n_integration.authentication import (
    N8nIntegrationAuthentication,
    N8nIntegrationTokenOnlyAuthentication,
)
from apps.modules.n8n_integration.serializers import (
    N8nApprovalImportSerializer,
    N8nBankExpenseImportSerializer,
    N8nBankRevenueImportSerializer,
    N8nCardExpenseImportSerializer,
    N8nCardRevenueImportSerializer,
    N8nClientDebtImportSerializer,
    N8nCashExpenseImportSerializer,
    N8nCashRevenueImportSerializer,
    N8nInvestCompanyImportSerializer,
    N8nNoteImportSerializer,
    N8nPayrollLineImportSerializer,
    N8nInvestPayoutScheduleImportSerializer,
    N8nInvestReturnImportSerializer,
    N8nProjectInvestmentImportSerializer,
    N8nRequestImportSerializer,
    N8nVendorImportSerializer,
)
from apps.modules.wallets.models import Wallet
from apps.modules.wallets.services import balances_for_tenant_channel
from apps.tenants.integration_settings import get_n8n_integration_settings
from apps.tenants.models import TenantModuleConfig
from apps.tenants.permissions import HasEffectiveModuleAccess

User = get_user_model()
logger = logging.getLogger(__name__)

# Reused HTTP client for outbound n8n calls. Keep-alive avoids a TCP+TLS handshake per request,
# which is the dominant cost when proxying through Traefik on the public hop.
_n8n_session = requests.Session()
_n8n_adapter = HTTPAdapter(pool_connections=20, pool_maxsize=50)
_n8n_session.mount("http://", _n8n_adapter)
_n8n_session.mount("https://", _n8n_adapter)


def _build_n8n_url(tenant, endpoint: str) -> tuple[str, str | None, str]:
    """
    Resolve the URL the backend should hit to reach an n8n webhook for a tenant.

    Returns (url, host_header_override, transport_label).
    Internal transport bypasses Traefik+TLS via the docker network; we still send Host
    as the public subdomain so any workflow that reads the Host header keeps working.
    """
    ep = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    base_internal = (getattr(settings, "N8N_INTERNAL_BASE_URL", "") or "").strip().rstrip("/")
    subdomain = getattr(tenant, "subdomain", "") or ""
    base_domain = getattr(settings, "BASE_DOMAIN", "") or ""
    if base_internal and subdomain:
        url = f"{base_internal}/{subdomain}{ep}"
        host_override = f"{subdomain}.{base_domain}" if base_domain else None
        return url, host_override, "internal"
    return f"https://{subdomain}.{base_domain}{ep}", None, "public"


def _n8n_error_payload(detail, *, error_type, error_location, reason=None, extra=None):
    payload = {
        "detail": detail,
        "error_type": error_type,
        "error_location": error_location,
    }
    if reason:
        payload["reason"] = reason
    if isinstance(extra, dict):
        payload.update(extra)
    return payload


def _n8n_integrity_error_payload(exc: IntegrityError) -> dict:
    """Human-readable DB message for n8n operators (duplicate keys, FK violations, etc.)."""
    raw = " ".join(str(a) for a in exc.args).strip() if exc.args else str(exc)
    raw = raw.strip() or "Database integrity constraint failed."
    return _n8n_error_payload(
        raw,
        error_type="integrity_error",
        error_location="database",
        reason="Database constraint violation",
        extra={"integrity_error": {"message": raw}},
    )


def _n8n_batch_item_summary(item: dict) -> dict:
    """Small stable subset of the failed batch row for logs and n8n expressions."""
    keys = (
        "external_id",
        "id",
        "pk",
        "doc_id",
        "line_no",
        "title",
        "expense_at",
        "expense_year",
        "revenue_date",
        "snapshot_at",
        "client",
        "client_id",
    )
    return {k: item[k] for k in keys if k in item}


def _n8n_batch_failure_response(idx, item, failed_status, failed_data, *, http_status=status.HTTP_400_BAD_REQUEST):
    payload = {
        "detail": "Batch failed. All changes rolled back.",
        "error_type": "batch_item_failed",
        "error_location": "batch",
        "reason": "One of batch items failed validation or persistence.",
        "failed_index": idx,
        "failed_status": failed_status,
        "failed_data": failed_data,
    }
    if isinstance(item, dict):
        payload["failed_item"] = item
        payload["failed_item_summary"] = _n8n_batch_item_summary(item)
    return Response(payload, status=http_status)


def _extract_bank_relink_candidate(payload: dict) -> tuple[str, int, int] | None:
    if not isinstance(payload, dict):
        return None
    raw_doc_no = payload.get("doc_no")
    raw_expense_year = payload.get("expense_year")
    raw_expense_id = payload.get("id")
    doc_no = str(raw_doc_no or "").strip()
    if not doc_no:
        return None
    try:
        expense_year = int(raw_expense_year)
        expense_id = int(raw_expense_id)
    except (TypeError, ValueError):
        return None
    return doc_no, expense_year, expense_id


def _relink_requests_to_bank_expenses(*, tenant, candidates: list[tuple[str, int, int]]) -> int:
    """
    Backfill canonical request->bank links after bank expense upserts.
    """
    if tenant is None or not candidates:
        return 0
    updated = 0
    deduped = set(candidates)
    for doc_no, expense_year, expense_id in deduped:
        expense = (
            BankExpense.objects.filter(tenant=tenant, pk=expense_id)
            .values("debit_turnover")
            .first()
        )
        if not expense:
            continue
        updated += Request.objects.filter(
            tenant=tenant,
            payment_type__in=(Request.PAYMENT_TYPE_TRANSFER, Request.PAYMENT_TYPE_TOPUP),
            expense_id=doc_no,
            expense_year=expense_year,
            amount=expense["debit_turnover"],
        ).filter(
            Q(expense_ref_id__isnull=True)
            | ~Q(expense_ref_id=expense_id)
            | ~Q(expense_ref_target=Request.EXPENSE_REF_TARGET_BANK)
        ).update(
            expense_ref_id=expense_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_BANK,
        )
    return updated


def _system_user():
    return User.objects.filter(pk=1).first()


def _n8n_actor_user_id(request) -> int:
    """User id forwarded to n8n proxies; JWT user when present, else system user."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user.id
    su = _system_user()
    return su.id if su is not None else 0


def _tenant_module_enabled(*, tenant, module_key: str) -> bool:
    return TenantModuleConfig.objects.filter(
        tenant=tenant,
        module_key=module_key,
        is_enabled=True,
    ).exists()


def _n8n_upsert(
    request,
    *,
    serializer_class,
    get_instance,
    other_tenant_conflict,
    build_create_kwargs,
    serializer_context_extra=None,
):
    su = _system_user()
    if su is None:
        return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    data = request.data
    pk = data.get("id")
    if pk not in (None, ""):
        try:
            pk = int(pk)
        except (TypeError, ValueError):
            return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
    else:
        pk = None

    ctx_base = {"request": request}
    if serializer_context_extra:
        ctx_base.update(serializer_context_extra)

    # Create without client PK when `id` is not provided.
    if pk is None:
        ser = serializer_class(data=data, context=ctx_base)
        ser.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                ser.save(**build_create_kwargs(request, su))
        except IntegrityError as exc:
            return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    instance = get_instance(pk)

    if instance:
        ser = serializer_class(instance=instance, data=data, partial=True, context=ctx_base)
        ser.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                ser.save()
        except IntegrityError as exc:
            return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(ser.data, status=status.HTTP_200_OK)

    if other_tenant_conflict(pk):
        return Response({"id": ["This ID already exists in another tenant."]}, status=status.HTTP_400_BAD_REQUEST)

    ser = serializer_class(data=data, context=ctx_base)
    ser.is_valid(raise_exception=True)
    try:
        with transaction.atomic():
            ser.save(id=pk, **build_create_kwargs(request, su))
    except IntegrityError as exc:
        return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
    return Response(ser.data, status=status.HTTP_201_CREATED)


class _N8nBaseView(APIView):
    """Upsert/read n8n API: integration token only (no JWT)."""

    authentication_classes = [N8nIntegrationTokenOnlyAuthentication]
    permission_classes = [AllowAny]

    def handle_exception(self, exc):
        location = getattr(self.request, "path", "unknown")
        if isinstance(exc, ValidationError):
            return Response(
                _n8n_error_payload(
                    "Validation failed.",
                    error_type="validation_error",
                    error_location=location,
                    reason="Request payload did not pass serializer validation.",
                    extra={"errors": exc.detail},
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if isinstance(exc, APIException):
            return super().handle_exception(exc)

        logger.exception("Unhandled n8n integration error at %s: %s", location, exc)
        return Response(
            _n8n_error_payload(
                "Unhandled server error.",
                error_type=exc.__class__.__name__,
                error_location=location,
                reason=str(exc),
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class _N8nBatchBaseView(_N8nBaseView):
    single_view_class = None
    skip_on_duplicate = False

    @staticmethod
    def _item_request(base_request, item_data):
        class _Req:
            data = item_data
            tenant = base_request.tenant
            META = base_request.META
            method = base_request.method
            user = base_request.user
            path = base_request.path
            GET = getattr(base_request, "GET", {})

        return _Req()

    def post(self, request):
        if not isinstance(request.data, list):
            return Response(
                _n8n_error_payload(
                    "Expected an array payload.",
                    error_type="invalid_payload_type",
                    error_location=request.path,
                    reason="Batch endpoint accepts only JSON array.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if self.single_view_class is None:
            return Response(
                _n8n_error_payload(
                    "Batch view is not configured.",
                    error_type="batch_not_configured",
                    error_location=request.path,
                    reason="single_view_class is missing for this batch endpoint.",
                ),
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        single_view = self.single_view_class()
        results = []
        skipped = 0
        with transaction.atomic():
            for idx, item in enumerate(request.data):
                if not isinstance(item, dict):
                    transaction.set_rollback(True)
                    return _n8n_batch_failure_response(
                        idx,
                        item,
                        status.HTTP_400_BAD_REQUEST,
                        {"detail": "Each array item must be an object."},
                    )
                item_request = self._item_request(request, item)
                try:
                    item_response = single_view.post(item_request)
                except ValidationError as exc:
                    transaction.set_rollback(True)
                    return _n8n_batch_failure_response(
                        idx,
                        item,
                        status.HTTP_400_BAD_REQUEST,
                        exc.detail,
                    )
                except Exception as exc:
                    logger.exception("n8n batch item processing failed: index=%s error=%s", idx, exc)
                    transaction.set_rollback(True)
                    return _n8n_batch_failure_response(
                        idx,
                        item,
                        status.HTTP_500_INTERNAL_SERVER_ERROR,
                        {
                            "detail": "Unhandled server error.",
                            "error_type": exc.__class__.__name__,
                            "error_message": str(exc),
                        },
                    )

                code = int(getattr(item_response, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR))
                if not 200 <= code < 300:
                    if self.skip_on_duplicate:
                        resp_data = getattr(item_response, "data", None)
                        if isinstance(resp_data, dict) and resp_data.get("error_type") == "integrity_error":
                            skipped += 1
                            continue
                    transaction.set_rollback(True)
                    return _n8n_batch_failure_response(
                        idx,
                        item,
                        code,
                        getattr(item_response, "data", None),
                    )

                results.append(
                    {
                        "index": idx,
                        "status": code,
                        "data": item_response.data,
                    }
                )

        return Response(
            {
                "count": len(results),
                "skipped": skipped,
                "results": results,
            },
            status=status.HTTP_200_OK,
        )


def _proxy_n8n_json(request, endpoint: str):
    tenant = getattr(request, "tenant", None)
    if not tenant:
        return Response(
            _n8n_error_payload(
                "No tenant.",
                error_type="tenant_missing",
                error_location=endpoint,
                reason="Tenant could not be resolved from request host/context.",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not settings.BASE_DOMAIN:
        return Response(
            _n8n_error_payload(
                "BASE_DOMAIN is not configured.",
                error_type="config_error",
                error_location=endpoint,
                reason="Missing BASE_DOMAIN setting.",
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    token = get_n8n_integration_settings(tenant=tenant).integration_token
    if not token:
        token = (getattr(settings, "N8N_INTEGRATION_TOKEN", None) or "").strip()
    if not token:
        return Response(
            _n8n_error_payload(
                "N8N_INTEGRATION_TOKEN is not configured.",
                error_type="config_error",
                error_location=endpoint,
                reason="Missing n8n integration token in tenant or global settings.",
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    url, host_override, transport = _build_n8n_url(tenant, endpoint)
    headers = {
        "Accept": "application/json",
        "X-N8N-Integration-Token": token,
        "X-Tenant": tenant.subdomain,
        "X-User-Id": str(_n8n_actor_user_id(request)),
    }
    if host_override:
        headers["Host"] = host_override

    started = time.perf_counter()
    try:
        resp = _n8n_session.get(url, params=request.GET, timeout=20, headers=headers)
    except requests.RequestException as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.warning(
            "n8n proxy failed: tenant=%s endpoint=%s transport=%s duration_ms=%.0f error=%s",
            tenant.subdomain, endpoint, transport, elapsed_ms, exc,
        )
        return Response(
            _n8n_error_payload(
                f"n8n request failed: {exc}",
                error_type="n8n_request_failed",
                error_location=endpoint,
                reason=exc.__class__.__name__,
            ),
            status=status.HTTP_502_BAD_GATEWAY,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "n8n proxy: tenant=%s endpoint=%s transport=%s status=%s duration_ms=%.0f",
        tenant.subdomain, endpoint, transport, resp.status_code, elapsed_ms,
    )

    if resp.status_code in (401, 403):
        return Response(
            _n8n_error_payload(
                "Forbidden by n8n.",
                error_type="n8n_forbidden",
                error_location=endpoint,
                reason=f"n8n returned HTTP {resp.status_code}.",
            ),
            status=status.HTTP_403_FORBIDDEN,
        )
    if resp.status_code >= 400:
        return Response(
            _n8n_error_payload(
                f"n8n error {resp.status_code}",
                error_type="n8n_bad_response",
                error_location=endpoint,
                reason="Upstream n8n endpoint returned non-success status.",
            ),
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        return Response(resp.json(), status=status.HTTP_200_OK)
    except ValueError:
        return Response(
            _n8n_error_payload(
                "Invalid JSON returned by n8n.",
                error_type="invalid_upstream_json",
                error_location=endpoint,
                reason="n8n response body is not valid JSON.",
            ),
            status=status.HTTP_502_BAD_GATEWAY,
        )


def _pnl_payload_backend_or_proxy(request, *, proxy_path: str, fetch_endpoint: str):
    """
    When tenant report settings say backend, return same payload as /api/reports/pnl/.
    Otherwise proxy to n8n at proxy_path.
    """
    tenant = getattr(request, "tenant", None)
    if not tenant:
        return Response(
            _n8n_error_payload(
                "No tenant.",
                error_type="tenant_missing",
                error_location=fetch_endpoint,
                reason="Tenant could not be resolved from request host/context.",
            ),
            status=status.HTTP_400_BAD_REQUEST,
        )
    from apps.modules.reports.services import fetch_n8n_report_payload, resolve_pnl_source_for_tenant

    try:
        pnl_source = resolve_pnl_source_for_tenant(tenant=tenant)
    except RuntimeError as exc:
        return Response(
            _n8n_error_payload(
                str(exc),
                error_type="report_config_error",
                error_location=fetch_endpoint,
                reason=exc.__class__.__name__,
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if pnl_source != "backend":
        return _proxy_n8n_json(request, proxy_path)

    if not settings.BASE_DOMAIN:
        return Response(
            _n8n_error_payload(
                "BASE_DOMAIN is not configured.",
                error_type="config_error",
                error_location=fetch_endpoint,
                reason="Missing BASE_DOMAIN setting.",
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    user = getattr(request, "user", None)
    user_id = int(getattr(user, "id", 0) or 0)
    try:
        payload = fetch_n8n_report_payload(
            tenant=tenant,
            user_id=user_id,
            endpoint=fetch_endpoint,
            query_params=dict(request.GET),
        )
    except RuntimeError as exc:
        return Response(
            _n8n_error_payload(
                str(exc),
                error_type="report_config_error",
                error_location=fetch_endpoint,
                reason=exc.__class__.__name__,
            ),
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except ValueError as exc:
        return Response(
            _n8n_error_payload(
                str(exc),
                error_type="report_payload_error",
                error_location=fetch_endpoint,
                reason=exc.__class__.__name__,
            ),
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return Response(payload, status=status.HTTP_200_OK)


class N8nPnlDataView(_N8nBaseView):
    def get(self, request):
        return _pnl_payload_backend_or_proxy(
            request,
            proxy_path="/pnl-data",
            fetch_endpoint="/n8n/pnl-data",
        )


class N8nCashflowDataView(_N8nBaseView):
    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/cashflow-data")


class PnlDataProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _pnl_payload_backend_or_proxy(
            request,
            proxy_path="/n8n/pnl-data",
            fetch_endpoint="/n8n/pnl-data",
        )


class CashflowDataProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/cashflow-data")


class AiChatProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        endpoint = "/n8n/aichat"
        if not tenant:
            return Response(
                _n8n_error_payload(
                    "No tenant.",
                    error_type="tenant_missing",
                    error_location=endpoint,
                    reason="Tenant could not be resolved from request host/context.",
                ),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not settings.BASE_DOMAIN:
            return Response(
                _n8n_error_payload(
                    "BASE_DOMAIN is not configured.",
                    error_type="config_error",
                    error_location=endpoint,
                    reason="Missing BASE_DOMAIN setting.",
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        question = str(request.data.get("question") or "").strip()
        if not question:
            return Response({"question": ["This field is required."]}, status=status.HTTP_400_BAD_REQUEST)

        raw_session_id = str(request.data.get("session_id") or "").strip()
        session_id = raw_session_id or uuid.uuid4().hex

        token = get_n8n_integration_settings(tenant=tenant).integration_token
        if not token:
            token = (getattr(settings, "N8N_INTEGRATION_TOKEN", None) or "").strip()
        if not token:
            return Response(
                _n8n_error_payload(
                    "N8N_INTEGRATION_TOKEN is not configured.",
                    error_type="config_error",
                    error_location=endpoint,
                    reason="Missing n8n integration token in tenant or global settings.",
                ),
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        url, host_override, transport = _build_n8n_url(tenant, endpoint)
        actor_id = _n8n_actor_user_id(request)
        payload = {
            "user": actor_id,
            "session_id": session_id,
            "question": question,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-N8N-Integration-Token": token,
            "X-Tenant": tenant.subdomain,
            "X-User-Id": str(actor_id),
        }
        if host_override:
            headers["Host"] = host_override

        started = time.perf_counter()
        try:
            resp = _n8n_session.post(url, json=payload, timeout=30, headers=headers)
        except requests.RequestException as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "n8n proxy failed: tenant=%s endpoint=%s transport=%s duration_ms=%.0f error=%s",
                tenant.subdomain, endpoint, transport, elapsed_ms, exc,
            )
            return Response(
                _n8n_error_payload(
                    f"n8n request failed: {exc}",
                    error_type="n8n_request_failed",
                    error_location=endpoint,
                    reason=exc.__class__.__name__,
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "n8n proxy: tenant=%s endpoint=%s transport=%s status=%s duration_ms=%.0f",
            tenant.subdomain, endpoint, transport, resp.status_code, elapsed_ms,
        )

        if resp.status_code in (401, 403):
            return Response(
                _n8n_error_payload(
                    "Forbidden by n8n.",
                    error_type="n8n_forbidden",
                    error_location=endpoint,
                    reason=f"n8n returned HTTP {resp.status_code}.",
                ),
                status=status.HTTP_403_FORBIDDEN,
            )
        if resp.status_code >= 400:
            return Response(
                _n8n_error_payload(
                    f"n8n error {resp.status_code}",
                    error_type="n8n_bad_response",
                    error_location=endpoint,
                    reason="Upstream n8n endpoint returned non-success status.",
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            data = resp.json()
        except ValueError:
            return Response(
                _n8n_error_payload(
                    "Invalid JSON returned by n8n.",
                    error_type="invalid_upstream_json",
                    error_location=endpoint,
                    reason="n8n response body is not valid JSON.",
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )
        payload = data
        if isinstance(data, list):
            payload = data[0] if data else {}
        if isinstance(payload, dict) and isinstance(payload.get("output"), dict):
            payload = payload.get("output")
        if not isinstance(payload, dict):
            return Response(
                _n8n_error_payload(
                    "Invalid JSON shape returned by n8n.",
                    error_type="invalid_upstream_json_shape",
                    error_location=endpoint,
                    reason="Expected object payload, or [ { output: {...} } ] wrapper.",
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )

        response_text = payload.get("response")
        if not isinstance(response_text, str):
            response_text = payload.get("reponse")
        if not isinstance(response_text, str):
            return Response(
                _n8n_error_payload(
                    "Missing AI response text in n8n payload.",
                    error_type="invalid_upstream_payload",
                    error_location=endpoint,
                    reason="Expected `response` (or legacy `reponse`) string field.",
                ),
                status=status.HTTP_502_BAD_GATEWAY,
            )

        normalized = dict(payload)
        normalized["session_id"] = str(payload.get("session_id") or session_id)
        normalized["response"] = response_text
        normalized["reponse"] = response_text
        return Response(normalized, status=status.HTTP_200_OK)


class N8nVendorUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        raw_acc = request.data.get("account_number", request.data.get("account_no"))
        account_no = (str(raw_acc).strip() if raw_acc is not None else "")

        # For vendor imports, support upsert-by-account when client id is omitted.
        if request.data.get("id") in (None, "") and account_no:
            existing = None
            existing = Vendor.objects.filter(tenant=tenant, account_number=account_no).first()
            if existing is not None:
                ser = N8nVendorImportSerializer(
                    instance=existing,
                    data=request.data,
                    partial=True,
                    context={"request": request},
                )
                ser.is_valid(raise_exception=True)
                try:
                    ser.save()
                except IntegrityError as exc:
                    return Response(
                        _n8n_integrity_error_payload(exc),
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                return Response(ser.data, status=status.HTTP_200_OK)

        def get_instance(pk):
            return Vendor.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Vendor.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nVendorImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nRequestUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return Request.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Request.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nRequestImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nAiRequestCreateView(APIView):
    """
    n8n gateway for AI assistants:
    accepts frontend-like user fields and runs the same create flow as portal.
    """

    module_key = "requests"
    authentication_classes = [N8nIntegrationAuthentication]
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def post(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = PortalRequestSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            request_obj = serializer.save(tenant=tenant, created_by=request.user)
            created_approvals = create_approval_rows_for_request(request_obj)
            if created_approvals and request_obj.status == Request.STATUS_DRAFT:
                _recalculate_request_status(request_obj)

        route_request_approvals(request_obj=request_obj)
        output = PortalRequestSerializer(request_obj, context={"request": request}).data
        return Response(output, status=status.HTTP_201_CREATED)


class N8nRequestAmortizationView(_N8nBaseView):
    def get(self, request):
        tenant = request.tenant
        request_id_raw = (request.query_params.get("request_id") or "").strip()
        amortized_only_raw = (request.query_params.get("amortized_only") or "1").strip().lower()
        amortized_only = amortized_only_raw not in {"0", "false", "no"}

        queryset = Request.objects.filter(tenant=tenant).order_by("-submitted_at")
        if request_id_raw:
            try:
                request_id = int(request_id_raw)
            except (TypeError, ValueError):
                return Response({"request_id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(id=request_id)
        if amortized_only:
            queryset = queryset.filter(amortization_months__gt=1)

        rows = []
        for req in queryset:
            rows.append(
                {
                    "id": req.id,
                    "title": req.title,
                    "status": req.status,
                    "amount": str(req.amount),
                    "currency": req.currency,
                    "billing_date": req.billing_date.isoformat() if req.billing_date else None,
                    "amortization_months": req.amortization_months,
                    "amortization_start_date": req.amortization_start_date.isoformat() if req.amortization_start_date else None,
                    "is_amortized": is_request_amortized(req),
                    "amortization_schedule": build_amortization_schedule_rows(req),
                }
            )
        return Response({"count": len(rows), "results": rows}, status=status.HTTP_200_OK)


class N8nApprovalUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return Approval.objects.filter(pk=pk, request__tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Approval.objects.filter(pk=pk).select_related("request").first()
            return o is not None and o.request.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {}

        return _n8n_upsert(
            request,
            serializer_class=N8nApprovalImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCashExpenseUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        su = _system_user()
        if su is None:
            return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        payload = dict(request.data)
        raw_id = payload.get("id")
        if raw_id not in (None, ""):
            try:
                int(raw_id)
            except (TypeError, ValueError):
                external_id = str(raw_id).strip()
                if not external_id:
                    return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
                payload.pop("id", None)
                payload.setdefault("external_id", external_id)

        # Prefer natural-key target when external_id/expense_year points to an existing row,
        # even if upstream sent a different numeric id.
        ser_probe = None
        if payload.get("external_id") not in (None, ""):
            ser_probe = N8nCashExpenseImportSerializer(data=payload, context={"request": request})
            ser_probe.is_valid(raise_exception=True)
            expense_year = ser_probe.validated_data.get("expense_year")
            external_id = str(ser_probe.validated_data.get("external_id") or "").strip()
            if external_id and expense_year is not None:
                existing_by_natural_key = CashExpense.objects.filter(
                    tenant=tenant,
                    external_id=external_id,
                    expense_year=expense_year,
                ).first()
                if existing_by_natural_key is not None and payload.get("id") not in (None, ""):
                    payload["id"] = existing_by_natural_key.id

        if payload.get("id") in (None, "") and payload.get("external_id") not in (None, ""):
            if ser_probe is None:
                create_ser = N8nCashExpenseImportSerializer(data=payload, context={"request": request})
                create_ser.is_valid(raise_exception=True)
            else:
                create_ser = ser_probe

            expense_year = create_ser.validated_data.get("expense_year")
            external_id = str(create_ser.validated_data.get("external_id") or "").strip()
            if external_id and expense_year is not None:
                existing = CashExpense.objects.filter(
                    tenant=tenant,
                    external_id=external_id,
                    expense_year=expense_year,
                ).first()
                if existing is not None:
                    update_ser = N8nCashExpenseImportSerializer(
                        instance=existing,
                        data=payload,
                        partial=True,
                        context={"request": request},
                    )
                    update_ser.is_valid(raise_exception=True)
                    try:
                        update_ser.save()
                    except IntegrityError as exc:
                        return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
                    return Response(update_ser.data, status=status.HTTP_200_OK)

            try:
                create_ser.save(tenant=request.tenant, created_by=su)
            except IntegrityError as exc:
                return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
            return Response(create_ser.data, status=status.HTTP_201_CREATED)

        def get_instance(pk):
            return CashExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CashExpense.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        class _Req:
            data = payload
            tenant = request.tenant
            META = request.META
            method = request.method
            user = request.user
            path = request.path

        return _n8n_upsert(
            _Req(),
            serializer_class=N8nCashExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCashRevenueUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        su = _system_user()
        if su is None:
            return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        payload = dict(request.data)
        raw_id = payload.get("id")
        raw_pk = payload.get("pk")
        source_year = payload.get("source_year")
        if source_year in ("",):
            source_year = None
        if source_year is not None:
            try:
                source_year = int(source_year)
                payload["source_year"] = source_year
            except (TypeError, ValueError):
                source_year = None
        # External source format support:
        # - pk: numeric DB id for upsert
        # - id: business external identifier
        if raw_id not in (None, "") and raw_pk not in (None, ""):
            try:
                payload["id"] = int(raw_pk)
                payload.setdefault("external_id", str(raw_id).strip())
                raw_id = payload.get("id")
            except (TypeError, ValueError):
                pass

        # Prefer natural-key target when external_id/source_year points to an existing row,
        # even if upstream sent a different numeric id.
        ser_probe = None
        if payload.get("external_id") not in (None, ""):
            ser_probe = N8nCashRevenueImportSerializer(data=payload, context={"request": request})
            ser_probe.is_valid(raise_exception=True)
            external_id = str(ser_probe.validated_data.get("external_id") or "").strip()
            effective_source_year = ser_probe.validated_data.get("source_year")
            if external_id:
                existing_qs = CashRevenue.objects.filter(tenant=tenant, external_id=external_id)
                if effective_source_year is not None:
                    existing_qs = existing_qs.filter(source_year=effective_source_year)
                existing_by_natural_key = existing_qs.first()
                if existing_by_natural_key is not None and payload.get("id") not in (None, ""):
                    payload["id"] = existing_by_natural_key.id
                    raw_id = payload.get("id")

        # Upsert by (external_id, source_year) when id is absent.
        if payload.get("id") in (None, "") and payload.get("external_id") not in (None, ""):
            if ser_probe is None:
                ser_probe = N8nCashRevenueImportSerializer(data=payload, context={"request": request})
                ser_probe.is_valid(raise_exception=True)
            external_id = str(ser_probe.validated_data.get("external_id") or "").strip()
            effective_source_year = ser_probe.validated_data.get("source_year")
            existing_qs = CashRevenue.objects.filter(tenant=tenant, external_id=external_id)
            if effective_source_year is not None:
                existing_qs = existing_qs.filter(source_year=effective_source_year)
            existing = existing_qs.first()
            if existing is not None:
                update_ser = N8nCashRevenueImportSerializer(
                    instance=existing,
                    data=payload,
                    partial=True,
                    context={"request": request},
                )
                update_ser.is_valid(raise_exception=True)
                try:
                    update_ser.save()
                except IntegrityError as exc:
                    return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
                return Response(update_ser.data, status=status.HTTP_200_OK)
            try:
                ser_probe.save(tenant=request.tenant, created_by=su)
            except IntegrityError as exc:
                return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
            return Response(ser_probe.data, status=status.HTTP_201_CREATED)

        if raw_id not in (None, ""):
            try:
                int(raw_id)
            except (TypeError, ValueError):
                external_id = str(raw_id).strip()
                if not external_id:
                    return Response({"id": ["Must be an integer."]}, status=status.HTTP_400_BAD_REQUEST)
                payload.pop("id", None)
                payload.setdefault("external_id", external_id)

                existing_qs = CashRevenue.objects.filter(tenant=tenant, external_id=external_id)
                if source_year is not None:
                    existing_qs = existing_qs.filter(source_year=source_year)
                existing = existing_qs.first()
                if existing is not None:
                    ser = N8nCashRevenueImportSerializer(
                        instance=existing,
                        data=payload,
                        partial=True,
                        context={"request": request},
                    )
                    ser.is_valid(raise_exception=True)
                    try:
                        ser.save()
                    except IntegrityError as exc:
                        return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
                    return Response(ser.data, status=status.HTTP_200_OK)

                ser = N8nCashRevenueImportSerializer(data=payload, context={"request": request})
                ser.is_valid(raise_exception=True)
                try:
                    ser.save(tenant=request.tenant, created_by=su)
                except IntegrityError as exc:
                    return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
                return Response(ser.data, status=status.HTTP_201_CREATED)

        def get_instance(pk):
            return CashRevenue.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CashRevenue.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        class _Req:
            data = payload
            tenant = request.tenant
            META = request.META
            method = request.method
            user = request.user
            path = request.path

        return _n8n_upsert(
            _Req(),
            serializer_class=N8nCashRevenueImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nBankExpenseUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return BankExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = BankExpense.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        response = _n8n_upsert(
            request,
            serializer_class=N8nBankExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )
        if 200 <= int(getattr(response, "status_code", 500)) < 300 and not getattr(
            request, "skip_bank_relink", False
        ):
            candidate = _extract_bank_relink_candidate(getattr(response, "data", None))
            if candidate is not None:
                _relink_requests_to_bank_expenses(tenant=tenant, candidates=[candidate])
        return response


class N8nBankRevenueUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return BankRevenue.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = BankRevenue.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nBankRevenueImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCardExpenseUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return CardExpense.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CardExpense.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nCardExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nCardRevenueUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return CardRevenue.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = CardRevenue.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nCardRevenueImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nClientsDebtUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        raw_snapshot_at = request.data.get("snapshot_at", request.data.get("date"))
        client_name = str(request.data.get("client") or "").strip()
        client_id = str(request.data.get("client_id") or "").strip()
        doc_type = str(request.data.get("doc_type") or "client_debt_total").strip() or "client_debt_total"
        snapshot_date = None
        snapshot_at_exact = None
        if isinstance(raw_snapshot_at, datetime):
            snapshot_at_exact = raw_snapshot_at
            snapshot_date = raw_snapshot_at.date()
        elif isinstance(raw_snapshot_at, date):
            snapshot_date = raw_snapshot_at
        elif raw_snapshot_at not in (None, ""):
            raw = str(raw_snapshot_at).strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                parsed_dt = datetime.fromisoformat(raw)
                snapshot_at_exact = parsed_dt
                snapshot_date = parsed_dt.date()
            except ValueError:
                try:
                    snapshot_date = date.fromisoformat(raw)
                except ValueError:
                    snapshot_date = None

        # Support upsert by natural key (snapshot_at date, client) when id is omitted.
        if request.data.get("id") in (None, "") and snapshot_date is not None:
            existing = None
            if snapshot_at_exact is not None and client_id:
                existing = ClientDebtSnapshot.objects.filter(
                    tenant=tenant,
                    snapshot_at=snapshot_at_exact,
                    doc_type=doc_type,
                    client_id=client_id,
                ).first()
            if existing is None and client_id:
                existing = ClientDebtSnapshot.objects.filter(
                    tenant=tenant,
                    snapshot_at__date=snapshot_date,
                    doc_type=doc_type,
                    client_id=client_id,
                ).first()
            if existing is None and client_name:
                existing = ClientDebtSnapshot.objects.filter(
                    tenant=tenant,
                    snapshot_at__date=snapshot_date,
                    client=client_name,
                ).first()
            if existing is not None:
                ser = N8nClientDebtImportSerializer(
                    instance=existing,
                    data=request.data,
                    partial=True,
                    context={"request": request},
                )
                ser.is_valid(raise_exception=True)
                try:
                    ser.save()
                except IntegrityError as exc:
                    return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
                return Response(ser.data, status=status.HTTP_200_OK)

        def get_instance(pk):
            return ClientDebtSnapshot.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = ClientDebtSnapshot.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nClientDebtImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nPayrollLineUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant
        raw_doc_id = request.data.get("doc_id")
        raw_line_no = request.data.get("line_no")
        doc_id = str(raw_doc_id or "").strip()
        line_no = None
        if raw_line_no not in (None, ""):
            try:
                line_no = int(raw_line_no)
            except (TypeError, ValueError):
                line_no = None

        # Support upsert by natural key (doc_id, line_no) when id is omitted.
        if request.data.get("id") in (None, "") and doc_id and line_no is not None:
            existing = PayrollLine.objects.filter(
                document__tenant=tenant,
                document__doc_id=doc_id,
                line_no=line_no,
            ).first()
            if existing is not None:
                ser = N8nPayrollLineImportSerializer(
                    instance=existing,
                    data=request.data,
                    partial=True,
                    context={"request": request},
                )
                ser.is_valid(raise_exception=True)
                try:
                    ser.save()
                except IntegrityError as exc:
                    return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
                return Response(ser.data, status=status.HTTP_200_OK)

        def get_instance(pk):
            return PayrollLine.objects.filter(pk=pk, document__tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = PayrollLine.objects.filter(pk=pk).select_related("document").first()
            return o is not None and o.document.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {}

        return _n8n_upsert(
            request,
            serializer_class=N8nPayrollLineImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nNoteUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return Note.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = Note.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nNoteImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nInvestReturnUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return InvestReturn.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = InvestReturn.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nInvestReturnImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
            serializer_context_extra={"skip_invest_return_billing_window": True},
        )


class N8nVendorBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nVendorUpsertView


class N8nRequestBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nRequestUpsertView


class N8nApprovalBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nApprovalUpsertView


class N8nCashExpenseBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCashExpenseUpsertView


class N8nCashRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCashRevenueUpsertView


class N8nBankExpenseBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nBankExpenseUpsertView
    skip_on_duplicate = True

    @staticmethod
    def _item_request(base_request, item_data):
        req = _N8nBatchBaseView._item_request(base_request, item_data)
        setattr(req, "skip_bank_relink", True)
        return req

    def post(self, request):
        response = super().post(request)
        if int(getattr(response, "status_code", 500)) != status.HTTP_200_OK:
            return response
        data = getattr(response, "data", {}) or {}
        results = data.get("results", []) if isinstance(data, dict) else []
        candidates: list[tuple[str, int, int]] = []
        for row in results:
            payload = row.get("data") if isinstance(row, dict) else None
            candidate = _extract_bank_relink_candidate(payload)
            if candidate is not None:
                candidates.append(candidate)
        if candidates:
            _relink_requests_to_bank_expenses(tenant=request.tenant, candidates=candidates)
        return response


class N8nBankRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nBankRevenueUpsertView
    skip_on_duplicate = True


class N8nCardExpenseBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCardExpenseUpsertView


class N8nCardRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nCardRevenueUpsertView


class N8nClientsDebtBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nClientsDebtUpsertView


class N8nPayrollLineBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nPayrollLineUpsertView


class N8nNoteBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nNoteUpsertView


class N8nInvestReturnPortalCreateView(_N8nBaseView):
    """
    Create an InvestReturn as the portal would: fetches CBU rate, enforces form-config
    type whitelist, and launches the configured approval chain via Telegram.
    Create-only — for historical imports with explicit IDs use the upsert endpoint.
    """

    def post(self, request):
        tenant = request.tenant
        su = _system_user()
        if su is None:
            return Response({"detail": "System user (pk=1) is missing."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        ser = InvestReturnSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)

        with transaction.atomic():
            invest_return = ser.save(tenant=tenant, created_by=su)
            create_approvals_for_invest_return(invest_return=invest_return)

        route_invest_return_approvals(invest_return=invest_return)
        return Response(InvestReturnSerializer(invest_return, context={"request": request}).data, status=status.HTTP_201_CREATED)


class N8nInvestReturnBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nInvestReturnUpsertView


class N8nInvestPayoutScheduleUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return InvestPayoutSchedule.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = InvestPayoutSchedule.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nInvestPayoutScheduleImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nInvestPayoutScheduleBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nInvestPayoutScheduleUpsertView


class N8nProjectInvestmentUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return ProjectInvestment.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = ProjectInvestment.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nProjectInvestmentImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nProjectInvestmentBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nProjectInvestmentUpsertView


class N8nInvestCompanyUpsertView(_N8nBaseView):
    def post(self, request):
        tenant = request.tenant

        def get_instance(pk):
            return InvestCompany.objects.filter(pk=pk, tenant=tenant).first()

        def other_tenant_conflict(pk):
            o = InvestCompany.objects.filter(pk=pk).first()
            return o is not None and o.tenant_id != tenant.id

        def build_create_kwargs(req, su):
            return {"tenant": req.tenant, "created_by": su}

        return _n8n_upsert(
            request,
            serializer_class=N8nInvestCompanyImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


class N8nInvestCompanyBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nInvestCompanyUpsertView


class N8nVendorListView(APIView):
    """Return vendors (id + name) grouped by payment_type for the current tenant.

    Vendor.kind only has cash/transfer; the latter applies to all
    non-cash payment types (Перечисление, Пополнение, Платежная карта).
    Auth: integration token only — no JWT, no user identity required.
    """

    authentication_classes = [N8nIntegrationTokenOnlyAuthentication]
    permission_classes = [AllowAny]

    @staticmethod
    def _vendor_rows(*, tenant, kind: str) -> list[dict]:
        return list(
            Vendor.objects.filter(tenant=tenant, kind=kind)
            .order_by("name")
            .values("id", "name")
        )

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_400_BAD_REQUEST)
        cash_vendors = self._vendor_rows(tenant=tenant, kind=Vendor.KIND_CASH)
        transfer_vendors = self._vendor_rows(tenant=tenant, kind=Vendor.KIND_TRANSFER)
        return Response(
            {
                Request.PAYMENT_TYPE_CASH: cash_vendors,
                Request.PAYMENT_TYPE_TRANSFER: transfer_vendors,
                Request.PAYMENT_TYPE_TOPUP: transfer_vendors,
                Request.PAYMENT_TYPE_CARD: transfer_vendors,
            }
        )


class N8nPaymentPurposeListView(APIView):
    """Return distinct payment purposes per payment_type for n8n pickers.

    Uses request form config (fast) and merges values from request history.
    Auth: integration token only — no JWT, no user identity required.
    """

    authentication_classes = [N8nIntegrationTokenOnlyAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(list_payment_purposes_by_payment_type(tenant_id=tenant.id))


_WALLET_BALANCE_CHANNELS = {
    "cash": (Wallet.Type.CASH, "cash"),
    "bank": (Wallet.Type.BANK, "bank"),
    "corporate_card": (Wallet.Type.CORPORATE_CARD, "corporate_card"),
}


class N8nWalletBalancesView(APIView):
    """Wallet running balances for n8n (same rows as /api/cash|bank|corporate-card/balances/).

    Auth: integration token only — no JWT.
    Query `channel`: optional `cash`, `bank`, or `corporate_card` — returns a flat list.
    Without `channel`: returns {"cash": [...], "bank": [...], "corporate_card": [...]}.
    Disabled tenant modules yield empty lists for that channel.
    """

    authentication_classes = [N8nIntegrationTokenOnlyAuthentication]
    permission_classes = [AllowAny]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_400_BAD_REQUEST)

        channel = (request.query_params.get("channel") or "").strip().lower()
        if channel:
            spec = _WALLET_BALANCE_CHANNELS.get(channel)
            if spec is None:
                return Response(
                    {
                        "channel": [
                            "Must be one of: cash, bank, corporate_card."
                        ]
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            wallet_type, module_key = spec
            if not _tenant_module_enabled(tenant=tenant, module_key=module_key):
                return Response([])
            return Response(
                balances_for_tenant_channel(tenant_id=tenant.id, wallet_type=wallet_type)
            )

        payload: dict[str, list] = {}
        for wallet_type, module_key in (
            (Wallet.Type.CASH, "cash"),
            (Wallet.Type.BANK, "bank"),
            (Wallet.Type.CORPORATE_CARD, "corporate_card"),
        ):
            if _tenant_module_enabled(tenant=tenant, module_key=module_key):
                payload[module_key] = balances_for_tenant_channel(
                    tenant_id=tenant.id,
                    wallet_type=wallet_type,
                )
            else:
                payload[module_key] = []
        return Response(payload)


class N8nUnmatchedExpensesView(_N8nBaseView):
    """Unmatched expenses + approval rules for n8n notification workflows."""

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_400_BAD_REQUEST)

        from apps.modules.requests.expense_compliance import (
            build_unmatched_expenses_payload,
            parse_unmatched_expenses_query_params,
        )

        try:
            date_from, date_to, channel, limit = parse_unmatched_expenses_query_params(
                query_params=request.query_params,
            )
        except ValueError as exc:
            if str(exc) == "channel":
                return Response(
                    {"channel": ["Must be one of: cash, bank, corporate_card, payroll."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {"date_from": ["Use YYYY-MM-DD format."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            build_unmatched_expenses_payload(
                tenant=tenant,
                date_from=date_from,
                date_to=date_to,
                channel=channel,
                limit=limit,
            )
        )
