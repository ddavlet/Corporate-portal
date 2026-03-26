from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.tenants.models import TenantModuleConfig, UserModulePermission, TenantMembership, Tenant

User = get_user_model()


class TenantModuleConfigSerializer(serializers.Serializer):
    module_key = serializers.CharField(max_length=100)
    is_enabled = serializers.BooleanField()


class TenantModuleConfigUpdateSerializer(serializers.Serializer):
    items = TenantModuleConfigSerializer(many=True)


class UserModulePermissionRowSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    can_access = serializers.BooleanField()


class UserModulePermissionUpdateRowSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    module_key = serializers.CharField(max_length=100)
    can_access = serializers.BooleanField()


class UserModulePermissionUpdateSerializer(serializers.Serializer):
    items = UserModulePermissionUpdateRowSerializer(many=True)


class UserModulePermissionRowResponseSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    module_key = serializers.CharField(max_length=100)
    can_access = serializers.BooleanField()


class ModuleCatalogRowSerializer(serializers.Serializer):
    module_key = serializers.CharField(max_length=100)
    display_name = serializers.CharField()
    tenant_enabled = serializers.BooleanField()
    user_allowed = serializers.BooleanField()
    effective_enabled = serializers.BooleanField()


