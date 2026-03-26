from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.tenants.models import TenantModuleConfig, UserModulePermission, TenantMembership
from apps.tenants.permissions import IsTenantAdmin
from apps.tenants.serializers import (
    TenantModuleConfigUpdateSerializer,
    UserModulePermissionUpdateSerializer,
)

from apps.modules.registry import list_modules

User = get_user_model()


class ModuleCatalogView(APIView):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant"}, status=status.HTTP_404_NOT_FOUND)

        # Tenant-enabled + per-user allowed + effective access.
        memberships = TenantMembership.objects.filter(tenant=tenant, user=request.user, is_active=True)
        is_tenant_admin = memberships.filter(role=TenantMembership.ROLE_TENANT_ADMIN).exists()

        out = []
        for m in list_modules():
            tenant_enabled = TenantModuleConfig.objects.filter(
                tenant=tenant, module_key=m["module_key"], is_enabled=True
            ).exists()
            user_allowed = UserModulePermission.objects.filter(
                tenant=tenant,
                user=request.user,
                module_key=m["module_key"],
                can_access=True,
            ).exists()
            effective_enabled = is_tenant_admin or (tenant_enabled and user_allowed)

            out.append(
                {
                    "module_key": m["module_key"],
                    "display_name": m["display_name"],
                    "tenant_enabled": tenant_enabled,
                    "user_allowed": user_allowed,
                    "effective_enabled": effective_enabled,
                }
            )

        return Response({"modules": out})


class TenantModuleConfigView(APIView):
    permission_classes = [IsTenantAdmin]

    def get(self, request):
        tenant = request.tenant
        items = []
        for m in list_modules():
            is_enabled = TenantModuleConfig.objects.filter(
                tenant=tenant, module_key=m["module_key"], is_enabled=True
            ).exists()
            items.append({"module_key": m["module_key"], "is_enabled": is_enabled})
        return Response({"items": items})

    def put(self, request):
        tenant = request.tenant
        serializer = TenantModuleConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        module_items = serializer.validated_data["items"]
        module_keys = [x["module_key"] for x in module_items]

        # Upsert rows.
        for row in module_items:
            cfg, _ = TenantModuleConfig.objects.update_or_create(
                tenant=tenant, module_key=row["module_key"], defaults={"is_enabled": row["is_enabled"]}
            )

        # Optional: disable all modules not present.
        # Keeping it explicit: only apply provided items for now.
        return Response({"items": list(serializer.validated_data["items"])})


class UserModulePermissionsView(APIView):
    permission_classes = [IsTenantAdmin]

    def get(self, request):
        tenant = request.tenant
        users = TenantMembership.objects.filter(tenant=tenant, is_active=True).select_related("user")

        rows = []
        for membership in users:
            for m in list_modules():
                can_access = UserModulePermission.objects.filter(
                    tenant=tenant, user=membership.user, module_key=m["module_key"], can_access=True
                ).exists()
                rows.append(
                    {
                        "user_id": membership.user_id,
                        "username": membership.user.username,
                        "module_key": m["module_key"],
                        "can_access": bool(can_access),
                    }
                )

        return Response({"items": rows})

    def put(self, request):
        tenant = request.tenant
        serializer = UserModulePermissionUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items = serializer.validated_data["items"]
        for row in items:
            user_id = row["user_id"]
            module_key = row["module_key"]
            can_access = row["can_access"]
            UserModulePermission.objects.update_or_create(
                tenant=tenant,
                user_id=user_id,
                module_key=module_key,
                defaults={"can_access": can_access},
            )

        return Response({"items": items})

