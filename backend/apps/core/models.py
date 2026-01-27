from django.conf import settings
from django.db import models

class Tenant(models.Model):
    name = models.CharField(max_length=120)
    subdomain = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)

    # пока достаточно (db_alias добавим позже, когда подключим company DB)
    # db_alias = models.CharField(max_length=64, blank=True, default="")

    def __str__(self):
        return f"{self.subdomain} ({self.name})"

class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    role = models.CharField(
        max_length=30,
        default="viewer",
        choices=[("admin", "admin"), ("manager", "manager"), ("viewer", "viewer")],
    )

    can_view_finance_report = models.BooleanField(default=False)

    class Meta:
        unique_together = [("user", "tenant")]

    def __str__(self):
        return f"{self.user_id} -> {self.tenant_id} ({self.role})"
