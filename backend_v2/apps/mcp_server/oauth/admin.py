from django.contrib import admin
from .models import OAuthClient, OAuthAuthorizationCode


@admin.register(OAuthClient)
class OAuthClientAdmin(admin.ModelAdmin):
    list_display = ("client_id", "client_name", "created_at")
    search_fields = ("client_id", "client_name")
    readonly_fields = ("client_id", "created_at")


@admin.register(OAuthAuthorizationCode)
class OAuthAuthorizationCodeAdmin(admin.ModelAdmin):
    list_display = ("code", "client", "user", "used", "expires_at", "created_at")
    list_filter = ("used",)
    search_fields = ("code", "user__username")
    readonly_fields = ("code", "client", "user", "created_at")
