import logging

import requests
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.reports.models import TenantReportSettings
from apps.modules.reports.pnl_builder import (
    ReportSettingsInvalid,
    compute_unassigned_payment_purposes,
    list_tenant_payment_purpose_pool,
    validate_pnl_config_dict,
)
from apps.modules.reports.registry import MODULE_KEY
from apps.modules.reports.services import fetch_n8n_report_payload
from apps.tenants.permissions import HasEffectiveModuleAccess, IsTenantAdmin

logger = logging.getLogger(__name__)


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
        except ValueError as exc:
            logger.warning(
                "reports proxy invalid json: tenant=%s report=%s error=%s",
                tenant.subdomain,
                self.report_name,
                exc,
            )
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 502
            logger.warning(
                "reports proxy upstream error: tenant=%s report=%s status=%s",
                tenant.subdomain,
                self.report_name,
                code,
            )
            if code in (401, 403):
                return Response({"detail": "Forbidden by n8n."}, status=status.HTTP_403_FORBIDDEN)
            return Response({"detail": f"n8n error {code}"}, status=status.HTTP_502_BAD_GATEWAY)
        except requests.RequestException as exc:
            logger.warning(
                "reports proxy request failed: tenant=%s report=%s error=%s",
                tenant.subdomain,
                self.report_name,
                exc,
            )
            return Response({"detail": f"n8n request failed: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

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


class TenantPnlPaymentPurposePoolView(APIView):
    """Distinct payment purpose strings for PnL bucket pickers (form config + request history)."""

    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "No tenant."}, status=status.HTTP_400_BAD_REQUEST)
        purposes = list_tenant_payment_purpose_pool(tenant_id=tenant.id)
        return Response({"purposes": purposes}, status=status.HTTP_200_OK)
