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

from apps.modules.reports.pnl_builder import list_tenant_payment_purpose_pool
from apps.modules.reports.registry import MODULE_KEY
from apps.modules.reports.report_kinds import REPORT_KINDS
from apps.modules.reports.report_rules import ReportSettingsInvalid
from apps.modules.reports.report_templates import TemplateNotFound, TemplateNotStatement
from apps.modules.reports.serializers import (
    ReportRulesPatchSerializer,
    ReportTemplateSettingsSerializer,
    StatementExportQuerySerializer,
    StatementLinesQuerySerializer,
    StatementQuerySerializer,
    StatementVendorsQuerySerializer,
)
from apps.modules.reports.services import (
    ReportSourceError,
    LineNotFound,
    TemplateNotAllowed,
    build_statement_for_tenant,
    export_statement_lines_xlsx,
    export_statement_xlsx,
    fetch_report_payload,
    get_report_rules,
    get_template_settings_response,
    list_statement_lines,
    list_statement_vendors,
    save_report_rules,
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

    report = "pnl"

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            payload = fetch_report_payload(
                tenant=tenant,
                user_id=request.user.id,
                report=self.report,
                query_params=request.GET,
            )
        except (ValueError, RuntimeError, requests.RequestException) as exc:
            return upstream_error_response(exc, tenant=tenant, report_name=self.report)

        payload["report"] = self.report
        return Response(payload, status=status.HTTP_200_OK)


class PnlReportView(_ReportsBaseView):
    report = "pnl"


class CashflowReportView(_ReportsBaseView):
    report = "cashflow"


def _unknown_report_response(report: str) -> Response:
    return Response({"detail": f"Отчёт «{report}» не найден."}, status=status.HTTP_404_NOT_FOUND)


class ReportRulesView(APIView):
    """A report's data source and calculation rules; every report keeps its own (tenant admin only)."""

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get(self, request, report: str):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        if report not in REPORT_KINDS:
            return _unknown_report_response(report)
        diagnostics = str(request.query_params.get("diagnostics") or "").strip() in {"1", "true", "yes"}
        return Response(get_report_rules(tenant=tenant, report=report, diagnostics=diagnostics), status=status.HTTP_200_OK)

    def patch(self, request, report: str):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        if report not in REPORT_KINDS:
            return _unknown_report_response(report)
        body = ReportRulesPatchSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            payload = save_report_rules(
                tenant=tenant,
                report=report,
                source=data.get("source"),
                rules=(data["rules"] or {}) if "rules" in data else None,
            )
        except ReportSettingsInvalid as exc:
            raise ValidationError({"rules": str(exc)}) from exc
        return Response(payload, status=status.HTTP_200_OK)


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
                vendor=data["vendor"],
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


class StatementVendorsView(APIView):
    module_key = MODULE_KEY
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        raw = request.query_params.dict()
        raw["date_from"] = raw.pop("from", None)
        raw["date_to"] = raw.pop("to", None)
        query = StatementVendorsQuerySerializer(data=raw)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        try:
            payload = list_statement_vendors(
                tenant=tenant,
                user_id=request.user.id,
                template_key=data["template"],
                report=data["report"],
                line_id=data["line"] or None,
                date_from=data["date_from"],
                date_to=data["date_to"],
                limit=data["limit"],
            )
        except (TemplateNotFound, TemplateNotStatement, TemplateNotAllowed) as exc:
            return _template_error_response(exc)
        except LineNotFound:
            return Response({"detail": "Строка отчёта не найдена."}, status=status.HTTP_404_NOT_FOUND)
        except ReportSourceError as exc:
            return upstream_error_response(exc.original, tenant=tenant, report_name=data["report"])
        return Response(payload, status=status.HTTP_200_OK)


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
                vendor=data["vendor"],
            )
        except (TemplateNotFound, TemplateNotStatement, TemplateNotAllowed) as exc:
            return _template_error_response(exc)
        except LineNotFound:
            return Response({"detail": "Строка отчёта не найдена."}, status=status.HTTP_404_NOT_FOUND)
        except ReportSourceError as exc:
            return upstream_error_response(exc.original, tenant=tenant, report_name=data["report"])
        return _file_response(file)
