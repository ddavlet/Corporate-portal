from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.notifications.models import PushSubscription
from apps.modules.notifications.push_services import (
    PushEndpointTaken,
    endpoint_hash,
    save_subscription,
    web_push_enabled,
)
from apps.modules.notifications.serializers import (
    ActionItemSerializer,
    PushSubscribeSerializer,
    PushUnsubscribeSerializer,
    TenantActionItemSerializer,
)
from apps.modules.notifications.services import collect_action_items, collect_all_action_items
from apps.tenants.models import TenantMembership
from apps.tenants.shared_host import is_shared_host, member_tenants


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


class AllActionItemsView(APIView):
    """Action items across all companies of the requesting user (shared portal host).

    Needs no company: only the user's active memberships in active tenants are read.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = collect_all_action_items(user=request.user)
        return Response({"count": len(items), "items": TenantActionItemSerializer(items, many=True).data})


class PushVapidPublicKeyView(APIView):
    """Public VAPID key for `PushManager.subscribe`; `enabled=false` when Web Push is off."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not web_push_enabled():
            return Response({"enabled": False, "public_key": None})
        return Response({"enabled": True, "public_key": settings.VAPID_PUBLIC_KEY})


class PushSubscribeView(APIView):
    """Upsert the device subscription of the requesting user (`push_services.save_subscription`).

    Only on the shared portal host: one subscription per device carries notifications of all
    companies, so it is not bound to a company. Endpoint and keys are never logged.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not is_shared_host(request):
            return Response(
                {"detail": "Уведомления включаются в общем приложении портала.", "code": "shared_host_only"},
                status=status.HTTP_409_CONFLICT,
            )
        if not web_push_enabled():
            return Response(
                {"detail": "Push-уведомления отключены на сервере.", "code": "push_disabled"},
                status=status.HTTP_409_CONFLICT,
            )
        if not member_tenants(user=request.user).exists():
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        serializer = PushSubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        keys = serializer.validated_data["keys"]
        try:
            created = save_subscription(
                user=request.user,
                endpoint=serializer.validated_data["endpoint"],
                p256dh=keys["p256dh"],
                auth=keys["auth"],
                user_agent=request.META.get("HTTP_USER_AGENT") or "",
            )
        except PushEndpointTaken:
            return Response(
                {"detail": "Это устройство подписано другим пользователем.", "code": "endpoint_taken"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"status": "created" if created else "updated"},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PushUnsubscribeView(APIView):
    """Revoke the requesting user's subscription for this endpoint (the row is kept)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PushUnsubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        subscription = PushSubscription.objects.filter(
            endpoint_hash=endpoint_hash(serializer.validated_data["endpoint"]), user=request.user
        ).first()
        if subscription is None:
            return Response({"detail": "Подписка не найдена.", "code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
        if subscription.revoked_at is None:
            PushSubscription.objects.filter(pk=subscription.pk, revoked_at__isnull=True).update(
                revoked_at=now, revoke_reason=PushSubscription.REVOKE_REASON_USER, updated_at=now
            )
        return Response(status=status.HTTP_204_NO_CONTENT)
