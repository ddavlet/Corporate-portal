from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from apps.tenants.models import TenantModuleConfig
from apps.tenants.permissions import IsTenantAdmin, role_allows_module
from apps.tenants.serializers import (
    TenantModuleConfigUpdateSerializer,
)

from apps.modules.registry import list_modules

User = get_user_model()


class ModuleCatalogView(APIView):
    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant"}, status=status.HTTP_404_NOT_FOUND)

        out = []
        for m in list_modules():
            module_key = m["module_key"]
            tenant_enabled = TenantModuleConfig.objects.filter(
                tenant=tenant, module_key=module_key, is_enabled=True
            ).exists()
            user_allowed = role_allows_module(user=request.user, tenant=tenant, module_key=module_key)
            effective_enabled = tenant_enabled and user_allowed

            out.append(
                {
                    "module_key": module_key,
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

