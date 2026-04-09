from django.conf import settings
from django.db import models

from apps.tenants.security import decrypt_secret, encrypt_secret


class Tenant(models.Model):
    name = models.CharField(max_length=120)
    subdomain = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)
    telegram_otp_enabled = models.BooleanField(default=False)
    telegram_bot_token_enc = models.TextField(blank=True, default="")

    def set_telegram_bot_token(self, token: str) -> None:
        self.telegram_bot_token_enc = encrypt_secret(token.strip())

    def get_telegram_bot_token(self) -> str:
        return decrypt_secret(self.telegram_bot_token_enc).strip()

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

    class Meta:
        unique_together = [("tenant", "user", "role")]

    def __str__(self) -> str:
        return f"{self.tenant_id}::{self.user_id}::{self.role}"


class TenantIntegrationConfig(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="integration_config")
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_tenant_integration_configs",
        null=True,
        blank=True,
    )

    telegram_approvals_bridge_dispatch_url = models.TextField(blank=True, default="")
    telegram_approvals_send_action = models.CharField(max_length=100, blank=True, default="send_approval_message")
    telegram_approvals_edit_action = models.CharField(max_length=100, blank=True, default="edit_approval_message")
    telegram_approvals_draft_notification_action = models.CharField(max_length=100, blank=True, default="")
    telegram_approvals_message_template = models.TextField(blank=True, default="")
    telegram_approvals_header_new_template = models.TextField(blank=True, default="")
    telegram_approvals_header_step_approved_template = models.TextField(blank=True, default="")
    telegram_approvals_header_fully_approved_template = models.TextField(blank=True, default="")
    telegram_approvals_header_closed_template = models.TextField(blank=True, default="")
    telegram_approvals_header_rejected_template = models.TextField(blank=True, default="")
    telegram_approvals_subheader_payment_responsible_template = models.TextField(blank=True, default="")
    telegram_approvals_subheader_rejected_by_template = models.TextField(blank=True, default="")
    telegram_approvals_bridge_token_enc = models.TextField(blank=True, default="")

    n8n_integration_token_enc = models.TextField(blank=True, default="")
    requests_file_gateway_token_enc = models.TextField(blank=True, default="")

    portal_feedback_telegram_chat_id = models.BigIntegerField(null=True, blank=True)
    portal_feedback_telegram_action = models.CharField(max_length=100, blank=True, default="")

    class Meta:
        db_table = "tenant_integration_configs"

    def set_telegram_approvals_bridge_token(self, token: str) -> None:
        self.telegram_approvals_bridge_token_enc = encrypt_secret((token or "").strip())

    def get_telegram_approvals_bridge_token(self) -> str:
        return decrypt_secret(self.telegram_approvals_bridge_token_enc).strip()

    def set_n8n_integration_token(self, token: str) -> None:
        self.n8n_integration_token_enc = encrypt_secret((token or "").strip())

    def get_n8n_integration_token(self) -> str:
        return decrypt_secret(self.n8n_integration_token_enc).strip()

    def set_requests_file_gateway_token(self, token: str) -> None:
        self.requests_file_gateway_token_enc = encrypt_secret((token or "").strip())

    def get_requests_file_gateway_token(self) -> str:
        return decrypt_secret(self.requests_file_gateway_token_enc).strip()

