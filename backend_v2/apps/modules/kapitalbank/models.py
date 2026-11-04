from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenants.models import Tenant
from apps.tenants.security import decrypt_secret, encrypt_secret


class KapitalbankConnection(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name="kapitalbank_connection")
    login = models.CharField(max_length=150)
    password_enc = models.TextField(blank=True, default="")
    is_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def set_password(self, raw: str) -> None:
        self.password_enc = encrypt_secret(raw)

    def get_password(self) -> str:
        return decrypt_secret(self.password_enc)

    @property
    def has_password(self) -> bool:
        return bool(self.password_enc)

    def __str__(self) -> str:
        return f"Kapitalbank connection for tenant {self.tenant_id}"


class KapitalbankAlertSettings(models.Model):
    """Singleton (pk=1): who receives the alerts. Each alert is sent by the bot of the account's
    tenant; ``bot_tenant`` is no longer used (kept to avoid a data-dropping migration)."""

    bot_tenant = models.ForeignKey(Tenant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    @classmethod
    def load(cls) -> KapitalbankAlertSettings:
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return "Kapitalbank alert settings"


class BankAccountLink(models.Model):
    PENDING = "pending"
    LINKED = "linked"
    IGNORED = "ignored"
    DECISION_CHOICES = [
        (PENDING, "Ожидает решения"),
        (LINKED, "Привязан"),
        (IGNORED, "Служебный"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="kapitalbank_links", db_index=False)
    account_no = models.CharField(max_length=20)
    branch = models.CharField(max_length=5)
    name = models.CharField(max_length=255, blank=True, default="")
    currency = models.CharField(max_length=10, blank=True, default="")
    last_balance = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    bank_state = models.CharField(max_length=64, blank=True, default="")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    decision = models.CharField(max_length=10, choices=DECISION_CHOICES, default=PENDING)
    ignore_reason = models.TextField(blank=True, default="")
    bank_account = models.ForeignKey(
        "wallets.BankAccount", null=True, blank=True, on_delete=models.PROTECT, related_name="kapitalbank_links"
    )
    card_account = models.ForeignKey(
        "wallets.CorporateCardAccount",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="kapitalbank_links",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # Statements are loaded only from this day on (None: no limit); its saldo_in becomes the
    # wallet's opening balance once, recorded by opening_synced_at.
    track_from = models.DateField(null=True, blank=True)
    opening_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "account_no", "branch"], name="kapitalbank_link_uniq_account"),
            models.CheckConstraint(
                condition=(
                    Q(decision="linked")
                    & (
                        (Q(bank_account__isnull=False) & Q(card_account__isnull=True))
                        | (Q(bank_account__isnull=True) & Q(card_account__isnull=False))
                    )
                )
                | (
                    Q(decision="ignored")
                    & ~Q(ignore_reason="")
                    & Q(bank_account__isnull=True)
                    & Q(card_account__isnull=True)
                )
                | (Q(decision="pending") & Q(bank_account__isnull=True) & Q(card_account__isnull=True)),
                name="kapitalbank_link_decision_consistent",
            ),
        ]

    @property
    def is_card(self) -> bool:
        return self.card_account_id is not None

    def wallet(self):
        if self.bank_account_id is not None:
            return self.bank_account.wallet
        if self.card_account_id is not None:
            return self.card_account.wallet
        return None

    def __str__(self) -> str:
        return f"{self.account_no}/{self.branch} ({self.decision})"


class AccountSyncState(models.Model):
    link = models.OneToOneField(BankAccountLink, on_delete=models.CASCADE, related_name="sync_state")
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.IntegerField(null=True, blank=True)
    last_error_message = models.TextField(blank=True, default="")
    consecutive_failures = models.IntegerField(default=0)
    mismatch_bank = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    mismatch_portal = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    mismatch_since = models.DateTimeField(null=True, blank=True)
    mismatch_alerted_at = models.DateTimeField(null=True, blank=True)
    down_alerted_at = models.DateTimeField(null=True, blank=True)


class SyncEvent(models.Model):
    IMPORTED = "imported"
    ERROR = "error"
    MISSING_DOCS = "missing_docs"
    ALERT_MISMATCH = "alert_mismatch"
    ALERT_RESOLVED = "alert_resolved"
    ALERT_DOWN = "alert_down"
    ALERT_OWN_TRANSFER = "alert_own_transfer"
    ALERT_NEW_ACCOUNT = "alert_new_account"
    ALERT_TYPE_CHANGED = "alert_type_change"
    KIND_CHOICES = [
        (IMPORTED, "Загружено"),
        (ERROR, "Ошибка"),
        (MISSING_DOCS, "Нет документов"),
        (ALERT_MISMATCH, "Алерт: расхождение остатка"),
        (ALERT_RESOLVED, "Алерт: расхождение устранено"),
        (ALERT_DOWN, "Алерт: банк недоступен"),
        (ALERT_OWN_TRANSFER, "Алерт: перевод между своими счетами"),
        (ALERT_NEW_ACCOUNT, "Алерт: новый счёт в банке"),
        (ALERT_TYPE_CHANGED, "Алерт: смена типа счёта"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="kapitalbank_events", db_index=False)
    link = models.ForeignKey(BankAccountLink, null=True, blank=True, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    day = models.DateField(null=True, blank=True)
    message = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    dedup_key = models.CharField(max_length=255, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["tenant", "created_at"], name="kapitalbank_event_tenant_ts")]
