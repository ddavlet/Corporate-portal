from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.investments.models import (
    InvestCompany,
    InvestPayoutSchedule,
    InvestPayoutScheduleShareLink,
    InvestReturn,
    ProjectInvestment,
)
from apps.modules.investments.serializers import (
    InvestCompanySerializer,
    InvestPayoutScheduleSerializer,
    InvestPayoutScheduleShareLinkSerializer,
    InvestReturnSerializer,
    PublicInvestPayoutScheduleShareViewSerializer,
    ProjectInvestmentSerializer,
)
from apps.tenants.permissions import HasEffectiveModuleAccess


class _InvestmentsTenantViewSet(viewsets.ModelViewSet):
    module_key = "investments"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get_queryset(self):
        tenant = getattr(self.request, "tenant", None)
        if not tenant:
            return self.queryset.none()
        return self.queryset.filter(tenant=tenant)

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant, created_by=self.request.user)


class InvestReturnViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestReturnSerializer
    queryset = InvestReturn.objects.all()


class InvestPayoutScheduleViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestPayoutScheduleSerializer
    queryset = InvestPayoutSchedule.objects.all()


class ProjectInvestmentViewSet(_InvestmentsTenantViewSet):
    serializer_class = ProjectInvestmentSerializer
    queryset = ProjectInvestment.objects.all()


class InvestCompanyViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestCompanySerializer
    queryset = InvestCompany.objects.all()


class InvestPayoutScheduleShareLinkViewSet(_InvestmentsTenantViewSet):
    serializer_class = InvestPayoutScheduleShareLinkSerializer
    queryset = InvestPayoutScheduleShareLink.objects.all()
    http_method_names = ["get", "post", "delete", "head", "options"]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(is_active=True).select_related("company")

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class PublicInvestPayoutScheduleByTokenView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token: str):
        link = (
            InvestPayoutScheduleShareLink.objects.filter(token=token, is_active=True)
            .select_related("company", "tenant")
            .first()
        )
        if not link:
            return Response({"detail": "Link not found."}, status=status.HTTP_404_NOT_FOUND)

        qs = InvestPayoutSchedule.objects.filter(tenant=link.tenant).select_related("company")
        if link.company_id:
            qs = qs.filter(company_id=link.company_id)
        if link.paid_filter == InvestPayoutScheduleShareLink.PaidFilter.PAID:
            qs = qs.filter(is_paid=True)
        elif link.paid_filter == InvestPayoutScheduleShareLink.PaidFilter.UNPAID:
            qs = qs.filter(is_paid=False)

        rows = [
            {
                "id": row.id,
                "payout_date": row.payout_date,
                "amount": row.amount,
                "is_paid": row.is_paid,
                "payment_amount": row.payment_amount,
                "comment": row.comment,
                "company": row.company_id,
                "company_name": row.company.name if row.company else "",
                "currency": row.currency,
            }
            for row in qs.order_by("payout_date", "id")
        ]
        return Response(
            {
                "filters": {
                    "company": link.company_id,
                    "company_name": link.company.name if link.company else "",
                    "tenant_name": link.tenant.name,
                    "paid_filter": link.paid_filter,
                },
                "rows": PublicInvestPayoutScheduleShareViewSerializer(rows, many=True).data,
            }
        )
