from __future__ import annotations

from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core.exceptions import ValidationError
from django.template.response import TemplateResponse
from django.utils import timezone

from apps.modules.kapitalbank.classification import set_account_type
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
    # The bank login is shown only on the change form (the owner edits it), not in the list.
    list_display = ("tenant", "password_state", "is_enabled", "updated_at")
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
    # Not a model field: the type of the linked portal bank account, saved through set_account_type
    # (which alerts the owner). Present only on a LINKED bank link (see has_account_type_field).
    account_type = forms.ChoiceField(
        label="Тип счёта портала",
        choices=BankAccount.AccountType.choices,
        required=False,
        help_text="Смена типа отправляет сообщение владельцу.",
    )

    class Meta:
        model = BankAccountLink
        fields = "__all__"

    @staticmethod
    def has_account_type_field(link) -> bool:
        return (
            link is not None
            and link.pk is not None
            and link.decision == BankAccountLink.LINKED
            and link.bank_account_id is not None
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.has_account_type_field(self.instance):
            self.fields["account_type"].initial = self.instance.bank_account.account_type
        else:
            self.fields.pop("account_type", None)
        tenant_id = self._known_tenant_id()
        if tenant_id:
            if "bank_account" in self.fields:
                self.fields["bank_account"].queryset = BankAccount.objects.filter(tenant_id=tenant_id)
            if "card_account" in self.fields:
                self.fields["card_account"].queryset = CorporateCardAccount.objects.filter(tenant_id=tenant_id)

    def _known_tenant_id(self):
        """Tenant before validation: the instance's, else the submitted (bound add form) or
        initial (?tenant=<id>) value. An unbound add form without it lists all accounts;
        clean() still rejects a foreign or mismatching one."""
        if self.instance.tenant_id:
            return self.instance.tenant_id
        raw = self.data.get(self.add_prefix("tenant")) if self.is_bound else self.initial.get("tenant")
        raw = getattr(raw, "pk", raw)
        try:
            return int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None

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

        # account_no/branch are read-only on the change form: fall back to the instance.
        account_no = (cleaned.get("account_no", self.instance.account_no) or "").strip()
        branch = (cleaned.get("branch", self.instance.branch) or "").strip()
        if bank is not None and (bank.account_no.strip() != account_no or bank.mfo.strip() != branch):
            self.add_error(
                "bank_account",
                f"Банковский счёт портала ({bank.account_no.strip() or '—'}, МФО {bank.mfo.strip() or '—'}) "
                f"не совпадает со счётом банка ({account_no}, МФО {branch}). "
                "Выберите счёт портала с тем же номером и МФО.",
            )
        if card is not None and card.external_ref.strip() != account_no:
            self.add_error(
                "card_account",
                f"Внешний номер карточного счёта портала ({card.external_ref.strip() or 'не задан'}) "
                f"не совпадает со счётом банка ({account_no}). "
                "Выберите карточный счёт, у которого внешний номер равен номеру счёта в банке.",
            )
        if self.errors:
            return cleaned

        if decision == BankAccountLink.LINKED:
            if bank is None and card is None:
                raise ValidationError("Для привязки выберите банковский или карточный счёт портала.")
            if bank is not None and card is not None:
                raise ValidationError("Выберите только один счёт: банковский или карточный.")
        elif decision == BankAccountLink.IGNORED:
            if not reason:
                self.add_error("ignore_reason", "Укажите причину, почему счёт служебный.")
            if bank is not None or card is not None:
                raise ValidationError("Служебный счёт не может быть привязан к счёту портала.")
        elif decision == BankAccountLink.PENDING:
            if bank is not None or card is not None:
                raise ValidationError("Счёт, ожидающий решения, не может быть привязан к счёту портала.")
        return cleaned


class IgnoreReasonForm(forms.Form):
    ignore_reason = forms.CharField(
        label="Причина",
        widget=forms.Textarea(attrs={"rows": 3, "cols": 80}),
        help_text="Будет записана у каждого выбранного счёта.",
    )


@admin.register(BankAccountLink)
class BankAccountLinkAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    form = BankAccountLinkForm
    actions = ("ignore_selected",)
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

    def get_fields(self, request, obj=None):
        fields = tuple(super().get_fields(request, obj))
        if BankAccountLinkForm.has_account_type_field(obj):
            fields += ("account_type",)
        return fields

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
        new_type = form.cleaned_data.get("account_type")
        if (
            change
            and new_type
            and "bank_account" not in form.changed_data
            and obj.decision == BankAccountLink.LINKED
            and obj.bank_account_id is not None
        ):
            # set_account_type is a no-op (no alert) when the type is unchanged; decided_by/at stay as they are.
            set_account_type(obj.bank_account, new_type, changed_by=request.user, now=timezone.now())

    @admin.action(description="Служебный (с общей причиной)")
    def ignore_selected(self, request, queryset):
        """Marks the selected PENDING links IGNORED with one reason. Linked and already ignored
        links are left as they are: unlinking a tracked account stays a per-account decision."""
        pending = queryset.filter(decision=BankAccountLink.PENDING)
        if not pending.exists():
            self.message_user(request, "Среди выбранных нет счетов, ожидающих решения.", messages.WARNING)
            return None
        form = IgnoreReasonForm(request.POST if "apply" in request.POST else None)
        if form.is_bound and form.is_valid():
            reason = form.cleaned_data["ignore_reason"].strip()
            ignored = pending.update(
                decision=BankAccountLink.IGNORED,
                ignore_reason=reason,
                decided_by=request.user,
                decided_at=timezone.now(),
            )
            self.message_user(
                request,
                f"Не отслеживаются: {ignored}. Пропущено (уже с решением): {queryset.count() - ignored}.",
                messages.SUCCESS,
            )
            return None
        context = {
            **self.admin_site.each_context(request),
            "title": "Отметить выбранные счета служебными",
            "opts": self.model._meta,
            "form": form,
            "pending": pending.select_related("tenant").order_by("tenant__subdomain", "account_no"),
            "skipped": queryset.exclude(decision=BankAccountLink.PENDING).count(),
            "selected": request.POST.getlist(ACTION_CHECKBOX_NAME),
            "select_across": request.POST.get("select_across", "0"),
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/kapitalbank/bankaccountlink/ignore_selected.html", context)


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
    list_select_related = ("tenant", "link")
    list_filter = (RecentPeriodFilter, "kind", "tenant")
    date_hierarchy = "created_at"
    search_fields = ("message",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(KapitalbankAlertSettings)
class KapitalbankAlertSettingsAdmin(NoDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "recipient")
    fields = ("recipient",)
    raw_id_fields = ("recipient",)

    def has_add_permission(self, request):
        return not KapitalbankAlertSettings.objects.exists()
