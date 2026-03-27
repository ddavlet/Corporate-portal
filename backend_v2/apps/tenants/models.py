from django.conf import settings
from django.db import models


class Tenant(models.Model):
    name = models.CharField(max_length=120)
    subdomain = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.subdomain} ({self.name})"


class TenantMembership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "tenant")]

    def __str__(self) -> str:
        return f"{self.user_id} -> {self.tenant_id}"


class TenantModuleConfig(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="module_configs")
    module_key = models.CharField(max_length=100)
    is_enabled = models.BooleanField(default=False)

    class Meta:
        unique_together = [("tenant", "module_key")]

    def __str__(self) -> str:
        return f"{self.tenant_id}::{self.module_key}={self.is_enabled}"


class TenantUserRole(models.Model):
    ROLE_REQUESTER = "requester"
    ROLE_APPROVER = "approver"
    ROLE_ADMIN = "admin"
    ROLE_DIRECTOR = "director"
    ROLE_CASHIER = "cashier"
    ROLE_ACCOUNTANT = "accountant"

    ROLE_CHOICES = [
        (ROLE_REQUESTER, ROLE_REQUESTER),
        (ROLE_APPROVER, ROLE_APPROVER),
        (ROLE_ADMIN, ROLE_ADMIN),
        (ROLE_DIRECTOR, ROLE_DIRECTOR),
        (ROLE_CASHIER, ROLE_CASHIER),
        (ROLE_ACCOUNTANT, ROLE_ACCOUNTANT),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="tenant_user_roles")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_roles")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    step = models.IntegerField()

    class Meta:
        unique_together = [("tenant", "user", "role")]

    def __str__(self) -> str:
        return f"{self.tenant_id}::{self.user_id}::{self.role} (step={self.step})"

