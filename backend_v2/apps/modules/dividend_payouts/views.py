from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.dividend_payouts.models import DividendPayoutRule
from apps.modules.dividend_payouts.serializers import PURPOSE_DUPLICATE_MESSAGE, DividendPayoutRuleSerializer
from apps.modules.dividend_payouts.services_config import options_payload
from apps.tenants.permissions import IsTenantAdminOrDirector


def _save(ser: DividendPayoutRuleSerializer, **kwargs):
    """Save; a concurrent duplicate hitting the DB constraint becomes a 400, not a 500."""
    try:
        with transaction.atomic():
            return ser.save(**kwargs)
    except IntegrityError:
        return None


def _duplicate_response() -> Response:
    return Response({"payment_purpose": [PURPOSE_DUPLICATE_MESSAGE]}, status=status.HTTP_400_BAD_REQUEST)


class DividendPayoutRuleListView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdminOrDirector]

    def get(self, request):
        rules = DividendPayoutRule.objects.filter(tenant=request.tenant).order_by("payment_purpose", "id")
        return Response(DividendPayoutRuleSerializer(rules, many=True).data)

    def post(self, request):
        ser = DividendPayoutRuleSerializer(data=request.data, context={"tenant": request.tenant})
        ser.is_valid(raise_exception=True)
        rule = _save(ser, tenant=request.tenant)
        if rule is None:
            return _duplicate_response()
        return Response(DividendPayoutRuleSerializer(rule).data, status=status.HTTP_201_CREATED)


class DividendPayoutRuleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdminOrDirector]

    def patch(self, request, rule_id: int):
        rule = get_object_or_404(DividendPayoutRule, pk=rule_id, tenant=request.tenant)
        ser = DividendPayoutRuleSerializer(rule, data=request.data, partial=True, context={"tenant": request.tenant})
        ser.is_valid(raise_exception=True)
        saved = _save(ser)
        if saved is None:
            return _duplicate_response()
        return Response(DividendPayoutRuleSerializer(saved).data)

    def delete(self, request, rule_id: int):
        # Rules are settings, not accounting data; links keep their history via SET_NULL.
        rule = get_object_or_404(DividendPayoutRule, pk=rule_id, tenant=request.tenant)
        rule.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class DividendPayoutOptionsView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdminOrDirector]

    def get(self, request):
        return Response(options_payload(request.tenant))
