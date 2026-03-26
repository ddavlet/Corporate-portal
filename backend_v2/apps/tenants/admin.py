from django import forms
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.db import transaction

from apps.modules.registry import list_modules
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, UserModulePermission


def _module_choices():
    mods = list_modules()
    return [(m["module_key"], f'{m["display_name"]} ({m["module_key"]})') for m in mods]


class TenantAdminForm(forms.ModelForm):
    enabled_modules = forms.MultipleChoiceField(
        label="Enabled modules",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=_module_choices,
        help_text="Modules enabled for this tenant (tenant-level toggle).",
    )

    class Meta:
        model = Tenant
        fields = ["name", "subdomain", "is_active", "enabled_modules"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            enabled = set(
                TenantModuleConfig.objects.filter(tenant=self.instance, is_enabled=True).values_list("module_key", flat=True)
            )
            self.fields["enabled_modules"].initial = sorted(enabled)

    @transaction.atomic
    def save(self, commit=True):
        tenant = super().save(commit=commit)

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


class TenantMembershipAdminForm(forms.ModelForm):
    allowed_modules = forms.MultipleChoiceField(
        label="User module access",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        choices=_module_choices,
        help_text="Per-user module access (only matters when tenant has the module enabled).",
    )

    class Meta:
        model = TenantMembership
        fields = ["user", "tenant", "is_active", "role", "allowed_modules"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            allowed = set(
                UserModulePermission.objects.filter(
                    tenant=self.instance.tenant,
                    user=self.instance.user,
                    can_access=True,
                ).values_list("module_key", flat=True)
            )
            self.fields["allowed_modules"].initial = sorted(allowed)

    @transaction.atomic
    def save(self, commit=True):
        membership = super().save(commit=commit)

        allowed_keys = set(self.cleaned_data.get("allowed_modules") or [])
        all_keys = [k for (k, _label) in _module_choices()]

        for key in all_keys:
            UserModulePermission.objects.update_or_create(
                tenant=membership.tenant,
                user=membership.user,
                module_key=key,
                defaults={"can_access": key in allowed_keys},
            )
        return membership


class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0
    autocomplete_fields = ("user",)
    fields = ("user", "role", "is_active")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    form = TenantAdminForm
    list_display = ("id", "subdomain", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("subdomain", "name")
    ordering = ("subdomain",)
    inlines = [TenantMembershipInline]
    readonly_fields = ("permissions_matrix_link",)
    fields = ("name", "subdomain", "is_active", "enabled_modules", "permissions_matrix_link")

    def permissions_matrix_link(self, obj: Tenant):
        if not obj or not obj.pk:
            return "Save tenant first to manage user permissions."
        url = reverse("admin:tenants_tenant_permissions_matrix", args=[obj.pk])
        return format_html('<a class="button" href="{}">Open permissions matrix</a>', url)

    permissions_matrix_link.short_description = "Permissions"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:tenant_id>/permissions-matrix/",
                self.admin_site.admin_view(self.permissions_matrix_view),
                name="tenants_tenant_permissions_matrix",
            ),
        ]
        return custom + urls

    @transaction.atomic
    def permissions_matrix_view(self, request: HttpRequest, tenant_id: int):
        tenant = Tenant.objects.get(pk=tenant_id)

        modules = list_modules()
        module_keys = [m["module_key"] for m in modules]

        memberships = (
            TenantMembership.objects.filter(tenant=tenant, is_active=True)
            .select_related("user")
            .order_by("user__username")
        )
        users = [m.user for m in memberships]

        existing = set(
            UserModulePermission.objects.filter(
                tenant=tenant,
                user_id__in=[u.id for u in users],
                module_key__in=module_keys,
                can_access=True,
            ).values_list("user_id", "module_key")
        )

        if request.method == "POST":
            for user in users:
                for key in module_keys:
                    field_name = f"perm__{user.id}__{key}"
                    desired = field_name in request.POST
                    UserModulePermission.objects.update_or_create(
                        tenant=tenant,
                        user=user,
                        module_key=key,
                        defaults={"can_access": desired},
                    )

            changepage = reverse("admin:tenants_tenant_change", args=[tenant.pk])
            return HttpResponseRedirect(changepage)

        # Build table rows for template.
        rows = []
        for user in users:
            row = {
                "user": user,
                "checks": {
                    key: ((user.id, key) in existing)
                    for key in module_keys
                },
            }
            rows.append(row)

        context = {
            **self.admin_site.each_context(request),
            "tenant": tenant,
            "modules": modules,
            "rows": rows,
            "title": f"Permissions matrix: {tenant.subdomain}",
        }
        return TemplateResponse(request, "admin/tenants/tenant/permissions_matrix.html", context)


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    form = TenantMembershipAdminForm
    list_display = ("id", "user", "tenant", "role", "is_active")
    list_filter = ("role", "is_active", "tenant")
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


@admin.register(UserModulePermission)
class UserModulePermissionAdmin(admin.ModelAdmin):
    list_display = ("id", "tenant", "user", "module_key", "can_access")
    list_filter = ("can_access", "module_key", "tenant")
    search_fields = ("user__username", "tenant__subdomain", "module_key")
    autocomplete_fields = ("user", "tenant")

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == "module_key":
            kwargs["choices"] = _module_choices()
        return super().formfield_for_choice_field(db_field, request, **kwargs)

