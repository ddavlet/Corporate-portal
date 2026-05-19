from django import forms
from django.contrib import admin
from django.db import transaction

from apps.modules.registry import list_modules
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole


def _module_choices():
    mods = list_modules()
    return [(m["module_key"], f'{m["display_name"]} ({m["module_key"]})') for m in mods]


class TenantAdminForm(forms.ModelForm):
    telegram_bot_token = forms.CharField(
        label="Telegram bot token (for OTP)",
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="Stored encrypted in DB. Leave empty to keep current token.",
    )
    telegram_bot_username = forms.CharField(
        label="Telegram bot username (for Login Widget)",
        required=False,
        help_text="Without @ prefix, for example: my_company_bot",
    )
    enabled_modules = forms.MultipleChoiceField(
        label="Enabled modules",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=_module_choices,
        help_text="Modules enabled for this tenant (tenant-level toggle).",
    )

    class Meta:
        model = Tenant
        fields = [
            "name",
            "subdomain",
            "is_active",
            "telegram_otp_enabled",
            "telegram_bot_token",
            "telegram_bot_username",
            "enabled_modules",
        ]

    def clean(self):
        cleaned = super().clean()
        enabled = set(cleaned.get("enabled_modules") or [])
        if "contracts" in enabled and "vendors" not in enabled:
            raise forms.ValidationError(
                {"enabled_modules": "Модуль «Договоры» требует включённый модуль «Поставщики»."}
            )
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            enabled = set(
                TenantModuleConfig.objects.filter(tenant=self.instance, is_enabled=True).values_list("module_key", flat=True)
            )
            self.fields["enabled_modules"].initial = sorted(enabled)
            self.fields["telegram_bot_token"].initial = self.instance.get_telegram_bot_token()
            self.fields["telegram_bot_username"].initial = self.instance.telegram_bot_username

    @transaction.atomic
    def save(self, commit=True):
        tenant = super().save(commit=commit)
        if tenant.pk is None:
            # Django admin calls ModelForm.save(commit=False) first; module upserts
            # below require a persisted tenant FK.
            tenant.save()
        token = (self.cleaned_data.get("telegram_bot_token") or "").strip()
        bot_username = (self.cleaned_data.get("telegram_bot_username") or "").strip().lstrip("@")
        if token:
            tenant.set_telegram_bot_token(token)
        tenant.telegram_bot_username = bot_username
        if commit:
            tenant.save(update_fields=["telegram_bot_token_enc", "telegram_bot_username"])

        enabled_keys = set(self.cleaned_data.get("enabled_modules") or [])
        all_keys = [k for (k, _label) in _module_choices()]

        # Upsert all module rows so the UI is stable and predictable.
        for key in all_keys:
            TenantModuleConfig.objects.update_or_create(
                tenant=tenant,
                module_key=key,
                defaults={"is_enabled": key in enabled_keys},
            )
        return tenant


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "is_active")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    form = TenantAdminForm
    list_display = ("id", "subdomain", "name", "is_active", "telegram_otp_enabled", "mcp_enabled")
    list_filter = ("is_active", "telegram_otp_enabled", "mcp_enabled")
    search_fields = ("subdomain", "name")
    ordering = ("subdomain",)
    # Roles: portal Settings ▸ Настройки пользователей (tenant admin).
    inlines = [TenantMembershipInline]
    fields = (
        "name",
        "subdomain",
        "is_active",
        "telegram_otp_enabled",
        "telegram_bot_token",
        "telegram_bot_username",
        "mcp_enabled",
        "enabled_modules",
    )


@admin.register(TenantUserRole)
class TenantUserRoleAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "user", "role")
    list_filter = ("role", "tenant")
    search_fields = ("tenant__subdomain", "tenant__name", "user__username", "user__email")
    autocomplete_fields = ("tenant", "user")

