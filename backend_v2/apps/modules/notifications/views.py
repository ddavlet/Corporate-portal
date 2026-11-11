from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.notifications.serializers import ActionItemSerializer
from apps.modules.notifications.services import collect_action_items
from apps.tenants.models import TenantMembership


class ActionItemsView(APIView):
    """Objects whose current approval step waits on the requesting user."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"count": 0, "items": []})
        has_membership = TenantMembership.objects.filter(
            tenant=tenant, user=request.user, is_active=True
        ).exists()
        if not has_membership:
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        items = collect_action_items(tenant=tenant, user=request.user)
        return Response({"count": len(items), "items": ActionItemSerializer(items, many=True).data})
