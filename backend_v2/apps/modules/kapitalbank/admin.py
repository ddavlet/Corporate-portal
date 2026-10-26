from __future__ import annotations

from datetime import timedelta

from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.modules.kapitalbank.models import (
    AccountSyncState,
    BankAccountLink,
    KapitalbankAlertSettings,
    KapitalbankConnection,
    SyncEvent,
)
from apps.modules.wallets.models import BankAccount, CorporateCardAccount


class NoDeleteAdminMixin:
    """This module's admin never deletes data: no delete permission, no bulk delete action."""

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


class KapitalbankConnectionForm(forms.ModelForm):
    password = forms.CharField(
        label="Пароль",
        required=False,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Оставьте пустым, чтобы не менять",
    )

    class Meta:
        model = KapitalbankConnection
        fields = ("tenant", "login", "is_enabled")

    def save(self, commit=True):
        obj = super().save(commit=False)
        raw = self.cleaned_data.get("password")
        if raw:
            obj.set_password(raw)
        if commit:
            obj.save()
        return obj


@admin.register(KapitalbankConnection)
class KapitalbankConnectionAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = KapitalbankConnectionForm
    fields = ("tenant", "login", "password", "is_enabled")
    list_display = ("tenant", "login", "password_state", "is_enabled", "updated_at")
    raw_id_fields = ("tenant",)

    @admin.display(description="Пароль")
    def password_state(self, obj):
        return "задан" if obj.has_password else "не задан"


class AccountSyncStateInline(admin.StackedInline):
    model = AccountSyncState
    extra = 0
    can_delete = False
    fields = (
        "last_success_at",
        "last_error_at",
        "last_error_code",
        "last_error_message",
        "consecutive_failures",
        "mismatch_bank",
        "mismatch_portal",
        "mismatch_since",
        "mismatch_alerted_at",
        "down_alerted_at",
    )
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BankAccountLinkForm(forms.ModelForm):
    class Meta:
        model = BankAccountLink
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tenant_id = self.instance.tenant_id
        if tenant_id:
            if "bank_account" in self.fields:
                self.fields["bank_account"].queryset = BankAccount.objects.filter(tenant_id=tenant_id)
            if "card_account" in self.fields:
                self.fields["card_account"].queryset = CorporateCardAccount.objects.filter(tenant_id=tenant_id)

    def _tenant_id(self):
        if self.instance.tenant_id:
            return self.instance.tenant_id
        tenant = self.cleaned_data.get("tenant")
        return tenant.pk if tenant else None

    def clean(self):
        cleaned = super().clean()
        decision = cleaned.get("decision")
        bank = cleaned.get("bank_account")
        card = cleaned.get("card_account")
        reason = (cleaned.get("ignore_reason") or "").strip()
        tenant_id = self._tenant_id()

        if tenant_id is not None:
            if bank is not None and bank.tenant_id != tenant_id:
                self.add_error("bank_account", "Банковский счёт принадлежит другому тенанту.")
            if card is not None and card.tenant_id != tenant_id:
                self.add_error("card_account", "Карточный счёт принадлежит другому тенанту.")
        if self.errors:
            return cleaned

        if decision == BankAccountLink.LINKED:
            if bank is None and card is None:
                raise ValidationError("Для привязки выберите банковский или карточный счёт портала.")
            if bank is not None and card is not None:
                raise ValidationError("Выберите только один счёт: банковский или карточный.")
        elif decision == BankAccountLink.IGNORED:
            if not reason:
                self.add_error("ignore_reason", "Укажите причину, почему счёт игнорируется.")
            if bank is not None or card is not None:
                raise ValidationError("Игнорируемый счёт не может быть привязан к счёту портала.")
        elif decision == BankAccountLink.PENDING:
            if bank is not None or card is not None:
                raise ValidationError("Счёт, ожидающий решения, не может быть привязан к счёту портала.")
        return cleaned


@admin.register(BankAccountLink)
class BankAccountLinkAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = BankAccountLinkForm
    list_display = ("tenant", "account_no", "name", "currency", "last_balance", "decision", "last_seen_at")
    list_filter = ("decision", "tenant")
    search_fields = ("account_no", "name")
    raw_id_fields = ("tenant",)
    inlines = [AccountSyncStateInline]
    fields = (
        "tenant",
        "account_no",
        "branch",
        "name",
        "currency",
        "last_balance",
        "bank_state",
        "decision",
        "ignore_reason",
        "bank_account",
        "card_account",
        "decided_by",
        "decided_at",
    )

    def get_readonly_fields(self, request, obj=None):
        bank_fields = ("name", "currency", "last_balance", "bank_state", "decided_by", "decided_at")
        if obj is not None:
            return ("tenant", "account_no", "branch") + bank_fields
        return bank_fields

    def save_model(self, request, obj, form, change):
        if not change or {"decision", "bank_account", "card_account"} & set(form.changed_data):
            obj.decided_by = request.user
            obj.decided_at = timezone.now()
        super().save_model(request, obj, form, change)


class RecentPeriodFilter(admin.SimpleListFilter):
    title = "период"
    parameter_name = "period"
    DEFAULT = "30d"
    DAYS = {"30d": 30, "7d": 7, "1d": 1}

    def lookups(self, request, model_admin):
        return (("30d", "30 дней"), ("7d", "7 дней"), ("1d", "Сутки"), ("all", "Все"))

    def _current(self):
        return self.value() or self.DEFAULT

    def queryset(self, request, queryset):
        days = self.DAYS.get(self._current())
        if days is None:
            return queryset
        return queryset.filter(created_at__gte=timezone.now() - timedelta(days=days))

    def choices(self, changelist):
        current = self._current()
        for lookup, title in self.lookup_choices:
            yield {
                "selected": current == lookup,
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": title,
            }


@admin.register(SyncEvent)
class SyncEventAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("created_at", "tenant", "link", "kind", "day", "message")
    list_filter = (RecentPeriodFilter, "kind", "tenant")
    date_hierarchy = "created_at"
    search_fields = ("message",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(KapitalbankAlertSettings)
class KapitalbankAlertSettingsAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "bot_tenant", "recipient")
    raw_id_fields = ("bot_tenant", "recipient")

    def has_add_permission(self, request):
        return not KapitalbankAlertSettings.objects.exists()
