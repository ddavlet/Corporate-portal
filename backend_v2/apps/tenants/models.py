from django.conf import settings
from django.db import models


class Tenant(models.Model):
    name = models.CharField(max_length=120)
    subdomain = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.subdomain} ({self.name})"


class TenantMembership(models.Model):
    ROLE_TENANT_ADMIN = "tenant_admin"
    ROLE_MEMBER = "member"

    ROLE_CHOICES = [
        (ROLE_TENANT_ADMIN, "tenant_admin"),
        (ROLE_MEMBER, "member"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    is_active = models.BooleanField(default=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default=ROLE_MEMBER)

    class Meta:
        unique_together = [("user", "tenant")]

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.tenant_id} ({self.role})"

    @property
    def is_tenant_admin(self) -> bool:
        return self.role == self.ROLE_TENANT_ADMIN


class TenantModuleConfig(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="module_configs")
    module_key = models.CharField(max_length=100)
    is_enabled = models.BooleanField(default=False)

    class Meta:
        unique_together = [("tenant", "module_key")]

    def __str__(self) -> str:
        return f"{self.tenant_id}::{self.module_key}={self.is_enabled}"


class UserModulePermission(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="user_module_permissions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="module_permissions")
    module_key = models.CharField(max_length=100)
    can_access = models.BooleanField(default=False)

    class Meta:
        unique_together = [("tenant", "user", "module_key")]

    def __str__(self) -> str:
        return f"{self.tenant_id}::{self.user_id}::{self.module_key}={self.can_access}"

