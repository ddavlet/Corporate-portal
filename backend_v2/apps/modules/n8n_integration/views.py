import logging
import uuid
from datetime import date, datetime

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.clients_debt.models import ClientDebtSnapshot
from apps.modules.payroll.models import PayrollLine
from apps.modules.cashier.models import CashExpense, CashRevenue
from apps.modules.corporate_card.models import CardExpense, CardRevenue
from apps.modules.investments.models import InvestCompany, InvestPayoutSchedule, InvestReturn, ProjectInvestment
from apps.modules.notes.models import Note
from apps.modules.requests.models import Approval, Request
from apps.modules.requests.amortization import build_amortization_schedule_rows, is_request_amortized
from apps.modules.vendors.models import Vendor
from apps.modules.n8n_integration.authentication import N8nIntegrationAuthentication
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
from apps.tenants.integration_settings import get_n8n_integration_settings
from apps.tenants.permissions import IsTenantAdmin

User = get_user_model()
logger = logging.getLogger(__name__)


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


def _system_user():
    return User.objects.filter(pk=1).first()


def _n8n_upsert(request, *, serializer_class, get_instance, other_tenant_conflict, build_create_kwargs):
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

    # Create without client PK when `id` is not provided.
    if pk is None:
        ser = serializer_class(data=data, context={"request": request})
        ser.is_valid(raise_exception=True)
        try:
            ser.save(**build_create_kwargs(request, su))
        except IntegrityError as exc:
            return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(ser.data, status=status.HTTP_201_CREATED)

    instance = get_instance(pk)
    ctx = {"request": request}

    if instance:
        ser = serializer_class(instance=instance, data=data, partial=True, context=ctx)
        ser.is_valid(raise_exception=True)
        try:
            ser.save()
        except IntegrityError as exc:
            return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
        return Response(ser.data, status=status.HTTP_200_OK)

    if other_tenant_conflict(pk):
        return Response({"id": ["This ID already exists in another tenant."]}, status=status.HTTP_400_BAD_REQUEST)

    ser = serializer_class(data=data, context=ctx)
    ser.is_valid(raise_exception=True)
    try:
        ser.save(id=pk, **build_create_kwargs(request, su))
    except IntegrityError as exc:
        return Response(_n8n_integrity_error_payload(exc), status=status.HTTP_400_BAD_REQUEST)
    return Response(ser.data, status=status.HTTP_201_CREATED)


class _N8nBaseView(APIView):
    authentication_classes = [N8nIntegrationAuthentication]
    permission_classes = [IsAuthenticated, IsTenantAdmin]

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

    url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/{endpoint.lstrip('/')}"
    try:
        resp = requests.get(
            url,
            params=request.GET,
            timeout=20,
            headers={
                "Accept": "application/json",
                "X-N8N-Integration-Token": token,
                "X-Tenant": tenant.subdomain,
                "X-User-Id": str(request.user.id),
            },
        )
    except requests.RequestException as exc:
        logger.warning("n8n report proxy request failed: tenant=%s endpoint=%s error=%s", tenant.subdomain, endpoint, exc)
        return Response(
            _n8n_error_payload(
                f"n8n request failed: {exc}",
                error_type="n8n_request_failed",
                error_location=endpoint,
                reason=exc.__class__.__name__,
            ),
            status=status.HTTP_502_BAD_GATEWAY,
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


class N8nPnlDataView(_N8nBaseView):
    def get(self, request):
        return _proxy_n8n_json(request, "/pnl-data")


class N8nCashflowDataView(_N8nBaseView):
    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/cashflow-data")


class PnlDataProxyView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_n8n_json(request, "/n8n/pnl-data")


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

        url = f"https://{tenant.subdomain}.{settings.BASE_DOMAIN}/{endpoint.lstrip('/')}"
        payload = {
            "user": request.user.id,
            "session_id": session_id,
            "question": question,
        }
        try:
            resp = requests.post(
                url,
                json=payload,
                timeout=30,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-N8N-Integration-Token": token,
                    "X-Tenant": tenant.subdomain,
                    "X-User-Id": str(request.user.id),
                },
            )
        except requests.RequestException as exc:
            logger.warning("n8n ai chat proxy request failed: tenant=%s endpoint=%s error=%s", tenant.subdomain, endpoint, exc)
            return Response(
                _n8n_error_payload(
                    f"n8n request failed: {exc}",
                    error_type="n8n_request_failed",
                    error_location=endpoint,
                    reason=exc.__class__.__name__,
                ),
                status=status.HTTP_502_BAD_GATEWAY,
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

        return _n8n_upsert(
            request,
            serializer_class=N8nBankExpenseImportSerializer,
            get_instance=get_instance,
            other_tenant_conflict=other_tenant_conflict,
            build_create_kwargs=build_create_kwargs,
        )


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


class N8nBankRevenueBatchUpsertView(_N8nBatchBaseView):
    single_view_class = N8nBankRevenueUpsertView


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
