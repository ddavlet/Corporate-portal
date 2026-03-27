from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.tenants.models import TenantModuleConfig, TenantMembership, Tenant

User = get_user_model()


class TenantModuleConfigSerializer(serializers.Serializer):
    module_key = serializers.CharField(max_length=100)
    is_enabled = serializers.BooleanField()


class TenantModuleConfigUpdateSerializer(serializers.Serializer):
    items = TenantModuleConfigSerializer(many=True)


class ModuleCatalogRowSerializer(serializers.Serializer):
    module_key = serializers.CharField(max_length=100)
    display_name = serializers.CharField()
    tenant_enabled = serializers.BooleanField()
    user_allowed = serializers.BooleanField()
    effective_enabled = serializers.BooleanField()


