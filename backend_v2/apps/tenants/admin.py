from django import forms
from django.contrib import admin
from django.db import transaction

from apps.modules.registry import list_modules
from apps.tenants.models import Tenant, TenantIntegrationConfig, TenantMembership, TenantModuleConfig, TenantUserRole


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
    enabled_modules = forms.MultipleChoiceField(
        label="Enabled modules",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=_module_choices,
        help_text="Modules enabled for this tenant (tenant-level toggle).",
    )

    class Meta:
        model = Tenant
        fields = ["name", "subdomain", "is_active", "telegram_otp_enabled", "telegram_bot_token", "enabled_modules"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            enabled = set(
                TenantModuleConfig.objects.filter(tenant=self.instance, is_enabled=True).values_list("module_key", flat=True)
            )
            self.fields["enabled_modules"].initial = sorted(enabled)
            self.fields["telegram_bot_token"].initial = self.instance.get_telegram_bot_token()

    @transaction.atomic
    def save(self, commit=True):
        tenant = super().save(commit=commit)
        token = (self.cleaned_data.get("telegram_bot_token") or "").strip()
        if token:
            tenant.set_telegram_bot_token(token)
            if commit:
                tenant.save(update_fields=["telegram_bot_token_enc"])

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


class TenantUserRoleInline(admin.TabularInline):
    model = TenantUserRole
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "role")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    form = TenantAdminForm
    list_display = ("id", "subdomain", "name", "is_active", "telegram_otp_enabled")
    list_filter = ("is_active", "telegram_otp_enabled")
    search_fields = ("subdomain", "name")
    ordering = ("subdomain",)
    inlines = [TenantMembershipInline, TenantUserRoleInline]
    fields = ("name", "subdomain", "is_active", "telegram_otp_enabled", "telegram_bot_token", "enabled_modules")


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "tenant", "is_active")
    list_filter = ("is_active", "tenant")
    search_fields = ("user__username", "user__email", "tenant__subdomain", "tenant__name")
    autocomplete_fields = ("user", "tenant")


@admin.register(TenantModuleConfig)
class TenantModuleConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "module_key", "is_enabled")
    list_filter = ("is_enabled", "module_key")
    search_fields = ("tenant__subdomain", "module_key")
    autocomplete_fields = ("tenant",)

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "module_key":
            kwargs["choices"] = _module_choices()
        return super().formfield_for_choice_field(db_field, request, **kwargs)


@admin.register(TenantUserRole)
class TenantUserRoleAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "user", "role")
    list_filter = ("tenant", "role")
    search_fields = ("tenant__subdomain", "user__username", "role")
    autocomplete_fields = ("tenant", "user")


@admin.register(TenantIntegrationConfig)
class TenantIntegrationConfigAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "updated_at", "updated_by")
    search_fields = ("tenant__subdomain", "tenant__name")
    autocomplete_fields = ("tenant", "updated_by")

