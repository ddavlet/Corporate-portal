import logging
from typing import TYPE_CHECKING

import requests
from django.http import HttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.cashflow_builder import (
    ReportSettingsInvalid as CashflowReportSettingsInvalid,
    compute_unassigned_payment_purposes_cashflow,
    validate_cashflow_config_dict,
    validate_cashflow_supplement_dict,
)
from apps.modules.reports.pnl_builder import (
    ReportSettingsInvalid,
    compute_unassigned_payment_purposes,
    list_tenant_payment_purpose_pool,
    validate_pnl_config_dict,
)
from apps.modules.reports.registry import MODULE_KEY
from apps.modules.reports.report_templates import TemplateNotFound, TemplateNotStatement
from apps.modules.reports.serializers import (
    ReportTemplateSettingsSerializer,
    StatementExportQuerySerializer,
    StatementLinesQuerySerializer,
    StatementQuerySerializer,
)
from apps.modules.reports.services import (
    ReportSourceError,
    LineNotFound,
    TemplateNotAllowed,
    build_statement_for_tenant,
    export_statement_lines_xlsx,
    export_statement_xlsx,
    fetch_n8n_report_payload,
    get_template_settings_response,
    list_statement_lines,
    save_template_settings,
)
from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdmin

if TYPE_CHECKING:
    from apps.modules.reports.xlsx_export import ExportFile

logger = logging.getLogger(__name__)


def upstream_error_response(exc: Exception, *, tenant, report_name: str) -> Response:
    """HTTP answer for a report payload that could not be loaded (shared by legacy and statement views)."""
    subdomain = getattr(tenant, "subdomain", "")
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else 502
        logger.warning("reports upstream error: tenant=%s report=%s status=%s", subdomain, report_name, code)
        if code in (401, 403):
            return Response({"detail": "Forbidden by n8n."}, status=status.HTTP_403_FORBIDDEN)
        return Response({"detail": f"n8n error {code}"}, status=status.HTTP_502_BAD_GATEWAY)
    if isinstance(exc, requests.RequestException):
        logger.warning("reports request failed: tenant=%s report=%s error=%s", subdomain, report_name, exc)
        return Response({"detail": f"n8n request failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)
    if isinstance(exc, RuntimeError):
        logger.warning("reports unavailable: tenant=%s report=%s error=%s", subdomain, report_name, exc)
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    logger.warning("reports invalid payload: tenant=%s report=%s error=%s", subdomain, report_name, exc)
    return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


class _ReportsBaseView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    report_path = "/n8n/pnl-data"
    report_name = "pnl"

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = fetch_n8n_report_payload(
                tenant=tenant,
                user_id=request.user.id,
                endpoint=self.report_path,
                query_params=request.GET,
            )
        except (ValueError, RuntimeError, requests.RequestException) as exc:
            return upstream_error_response(exc, tenant=tenant, report_name=self.report_name)

        payload["report"] = self.report_name
        return Response(payload, status=status.HTTP_200_OK)


class PnlReportView(_ReportsBaseView):
    report_path = "/n8n/pnl-data"
    report_name = "pnl"


class CashflowReportView(_ReportsBaseView):
    report_path = "/n8n/cashflow-data"
    report_name = "cashflow"


class TenantReportSettingsConfigView(APIView):
    """
    Per-tenant PnL source (n8n vs backend) and backend filters — tenant admin only.
    """

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    @staticmethod
    def _serialize(row: TenantReportSettings) -> dict:
        return {
            "pnl_source": row.pnl_source,
            "pnl_config": row.pnl_config if isinstance(row.pnl_config, dict) else {},
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        row, _ = TenantReportSettings.objects.get_or_create(
            tenant=tenant,
            defaults={
                "pnl_source": TenantReportSettings.PNL_SOURCE_N8N,
                "pnl_config": {},
            },
        )
        data = self._serialize(row)
        if str(request.query_params.get("pnl_diagnostics") or "").strip() in {"1", "true", "yes"}:
            cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
            try:
                unassigned = compute_unassigned_payment_purposes(tenant_id=tenant.id, cfg=cfg)
                data["pnl_diagnostics"] = {"unassigned_payment_purposes": unassigned}
            except ReportSettingsInvalid as exc:
                data["pnl_diagnostics"] = {"error": str(exc)}
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)

        row, _ = TenantReportSettings.objects.get_or_create(
            tenant=tenant,
            defaults={
                "pnl_source": TenantReportSettings.PNL_SOURCE_N8N,
                "pnl_config": {},
            },
        )

        body = request.data if isinstance(request.data, dict) else {}
        new_source = row.pnl_source
        if "pnl_source" in body:
            raw = str(body.get("pnl_source") or "").strip().lower()
            if raw not in {TenantReportSettings.PNL_SOURCE_N8N, TenantReportSettings.PNL_SOURCE_BACKEND}:
                raise ValidationError({"pnl_source": "Must be 'n8n' or 'backend'."})
            new_source = raw

        new_cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
        if "pnl_config" in body:
            cfg_in = body.get("pnl_config")
            if cfg_in is None:
                new_cfg = {}
            elif not isinstance(cfg_in, dict):
                raise ValidationError({"pnl_config": "Must be a JSON object."})
            else:
                new_cfg = cfg_in

        if new_source == TenantReportSettings.PNL_SOURCE_BACKEND:
            try:
                validate_pnl_config_dict(new_cfg)
            except ReportSettingsInvalid as exc:
                raise ValidationError({"pnl_config": str(exc)}) from exc

        row.pnl_source = new_source
        row.pnl_config = new_cfg
        row.save(update_fields=["pnl_source", "pnl_config", "updated_at"])

        return Response(self._serialize(row), status=status.HTTP_200_OK)


class TenantCashflowReportSettingsConfigView(APIView):
    """
    Per-tenant Cashflow source (n8n vs backend). Filters come from ``pnl_config`` (same as backend PnL).
    ``cashflow_config`` holds Cashflow-only settings (e.g. opening_balance).
    """

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    @staticmethod
    def _serialize(row: TenantReportSettings) -> dict:
        pnl_cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
        cf_cfg = row.cashflow_config if isinstance(row.cashflow_config, dict) else {}
        return {
            "cashflow_source": row.cashflow_source,
            "pnl_config": pnl_cfg,
            "cashflow_config": cf_cfg,
            "uses_pnl_config": True,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        row, _ = TenantReportSettings.objects.get_or_create(
            tenant=tenant,
            defaults={
                "pnl_source": TenantReportSettings.PNL_SOURCE_N8N,
                "pnl_config": {},
                "cashflow_source": TenantReportSettings.CASHFLOW_SOURCE_N8N,
                "cashflow_config": {},
            },
        )
        data = self._serialize(row)
        if str(request.query_params.get("cashflow_diagnostics") or "").strip() in {"1", "true", "yes"}:
            cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
            try:
                unassigned = compute_unassigned_payment_purposes_cashflow(tenant_id=tenant.id, cfg=cfg)
                data["cashflow_diagnostics"] = {"unassigned_payment_purposes": unassigned}
            except CashflowReportSettingsInvalid as exc:
                data["cashflow_diagnostics"] = {"error": str(exc)}
        return Response(data, status=status.HTTP_200_OK)

    def patch(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)

        row, _ = TenantReportSettings.objects.get_or_create(
            tenant=tenant,
            defaults={
                "pnl_source": TenantReportSettings.PNL_SOURCE_N8N,
                "pnl_config": {},
                "cashflow_source": TenantReportSettings.CASHFLOW_SOURCE_N8N,
                "cashflow_config": {},
            },
        )

        body = request.data if isinstance(request.data, dict) else {}
        new_source = row.cashflow_source
        if "cashflow_source" in body:
            raw = str(body.get("cashflow_source") or "").strip().lower()
            if raw not in {TenantReportSettings.CASHFLOW_SOURCE_N8N, TenantReportSettings.CASHFLOW_SOURCE_BACKEND}:
                raise ValidationError({"cashflow_source": "Must be 'n8n' or 'backend'."})
            new_source = raw

        if new_source == TenantReportSettings.CASHFLOW_SOURCE_BACKEND:
            cfg = row.pnl_config if isinstance(row.pnl_config, dict) else {}
            try:
                validate_cashflow_config_dict(cfg)
            except CashflowReportSettingsInvalid as exc:
                raise ValidationError(
                    {"pnl_config": f"Настройте отчёт PnL (backend): {exc}"}
                ) from exc

        update_fields = ["cashflow_source", "updated_at"]
        if "cashflow_config" in body:
            cf_in = body.get("cashflow_config")
            if cf_in is None:
                new_cf_merged: dict = {}
            elif not isinstance(cf_in, dict):
                raise ValidationError({"cashflow_config": "Must be a JSON object."})
            else:
                base_cf = row.cashflow_config if isinstance(row.cashflow_config, dict) else {}
                new_cf_merged = {**base_cf, **cf_in}
            try:
                validate_cashflow_supplement_dict(new_cf_merged)
            except CashflowReportSettingsInvalid as exc:
                raise ValidationError({"cashflow_config": str(exc)}) from exc
            row.cashflow_config = new_cf_merged
            update_fields.append("cashflow_config")

        row.cashflow_source = new_source
        row.save(update_fields=update_fields)

        return Response(self._serialize(row), status=status.HTTP_200_OK)


class TenantPnlPaymentPurposePoolView(APIView):
    """Distinct payment purpose strings for PnL bucket pickers (form config + request history).

    Optional query ``for_pnl_payment_types``: comma-separated payment type values
    (same strings as ``request_payment_types_for_pnl`` / ``Request.PAYMENT_TYPE_CHOICES``).
    When omitted, purposes from all payment types are returned.
    """

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        raw = request.query_params.get("for_pnl_payment_types")
        if raw is None:
            for_types: list[str] | None = None
        else:
            for_types = [p.strip() for p in str(raw).split(",") if p.strip()]
        purposes = list_tenant_payment_purpose_pool(
            tenant_id=tenant.id,
            for_pnl_payment_types=for_types,
        )
        return Response({"purposes": purposes}, status=status.HTTP_200_OK)


class ReportTemplatesView(APIView):
    """Templates the tenant may use; admins change the default and the allowed list."""

    module_key = MODULE_KEY

    def get_permissions(self):
        if self.request.method == "PATCH":
            return [IsAuthenticated(), IsTenantAdmin()]
        return [IsAuthenticated(), HasEffectiveModuleAccess()]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(get_template_settings_response(tenant=tenant), status=status.HTTP_200_OK)

    def patch(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ReportTemplateSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(save_template_settings(tenant=tenant, **serializer.validated_data), status=status.HTTP_200_OK)


def _template_error_response(exc: Exception) -> Response:
    if isinstance(exc, TemplateNotAllowed):
        return Response({"detail": "Шаблон недоступен для этой компании."}, status=status.HTTP_403_FORBIDDEN)
    if isinstance(exc, TemplateNotFound):
        return Response({"detail": f"Шаблон «{exc}» не найден."}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"detail": "Шаблон не поддерживает этот отчёт."}, status=status.HTTP_400_BAD_REQUEST)


class StatementView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        query = StatementQuerySerializer(data=request.query_params, context={"today": timezone.localdate()})
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            payload = build_statement_for_tenant(
                tenant=tenant,
                user_id=request.user.id,
                template_key=data["template"],
                report=data["report"],
                period_spec=query.period_spec(),
                refresh=data["refresh"],
                include_warnings=IsTenantAdmin().has_permission(request, self),
            )
        except (TemplateNotFound, TemplateNotStatement, TemplateNotAllowed) as exc:
            return _template_error_response(exc)
        except ReportSourceError as exc:
            return upstream_error_response(exc.original, tenant=tenant, report_name=data["report"])
        return Response(payload, status=status.HTTP_200_OK)


class StatementLinesView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        raw = request.query_params.dict()
        raw["date_from"] = raw.pop("from", None)
        raw["date_to"] = raw.pop("to", None)
        query = StatementLinesQuerySerializer(data=raw)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            payload = list_statement_lines(
                tenant=tenant,
                user_id=request.user.id,
                template_key=data["template"],
                report=data["report"],
                line_id=data["line"] or None,
                date_from=data["date_from"],
                date_to=data["date_to"],
                query=data["q"],
                page=data["page"],
                page_size=data["page_size"],
                source=data["source"] or None,
            )
        except (TemplateNotFound, TemplateNotStatement, TemplateNotAllowed) as exc:
            return _template_error_response(exc)
        except LineNotFound:
            return Response({"detail": "Строка отчёта не найдена."}, status=status.HTTP_404_NOT_FOUND)
        except ReportSourceError as exc:
            return upstream_error_response(exc.original, tenant=tenant, report_name=data["report"])
        return Response(payload, status=status.HTTP_200_OK)


def _file_response(file: "ExportFile") -> HttpResponse:
    response = HttpResponse(file.content, content_type=file.content_type)
    response["Content-Disposition"] = content_disposition_header(True, file.filename)
    response["Cache-Control"] = "no-store"
    return response


def _export_author(user) -> str:
    return (user.get_full_name() or "").strip() or user.get_username()


class StatementExportView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        query = StatementExportQuerySerializer(data=request.query_params, context={"today": timezone.localdate()})
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            file = export_statement_xlsx(
                tenant=tenant,
                user_id=request.user.id,
                template_key=data["template"],
                report=data["report"],
                period_spec=query.period_spec(),
                units=data["units"],
                author=_export_author(request.user),
            )
        except (TemplateNotFound, TemplateNotStatement, TemplateNotAllowed) as exc:
            return _template_error_response(exc)
        except ReportSourceError as exc:
            return upstream_error_response(exc.original, tenant=tenant, report_name=data["report"])
        return _file_response(file)


class StatementLinesExportView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        raw = request.query_params.dict()
        raw["date_from"] = raw.pop("from", None)
        raw["date_to"] = raw.pop("to", None)
        query = StatementLinesQuerySerializer(data=raw)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            file = export_statement_lines_xlsx(
                tenant=tenant,
                user_id=request.user.id,
                template_key=data["template"],
                report=data["report"],
                line_id=data["line"] or None,
                date_from=data["date_from"],
                date_to=data["date_to"],
                query=data["q"],
                source=data["source"] or None,
                author=_export_author(request.user),
            )
        except (TemplateNotFound, TemplateNotStatement, TemplateNotAllowed) as exc:
            return _template_error_response(exc)
        except LineNotFound:
            return Response({"detail": "Строка отчёта не найдена."}, status=status.HTTP_404_NOT_FOUND)
        except ReportSourceError as exc:
            return upstream_error_response(exc.original, tenant=tenant, report_name=data["report"])
        return _file_response(file)
