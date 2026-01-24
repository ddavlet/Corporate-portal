from django.contrib import admin
from .models import Tenant, Membership

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("id", "subdomain", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("subdomain", "name")
    ordering = ("subdomain",)

@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "tenant", "role", "is_active")
    list_filter = ("role", "is_active", "tenant")
    search_fields = ("user__username", "user__email", "tenant__subdomain", "tenant__name")
    autocomplete_fields = ("user", "tenant")
