import logging

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.reports.registry import MODULE_KEY
from apps.modules.reports.services import fetch_n8n_report_payload
from apps.tenants.permissions import HasEffectiveModuleAccess

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
