from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group

from apps.accounts.models import User

admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Profile", {"fields": ("full_name",)}),
        ("Telegram", {"fields": ("telegram_chat_id", "telegram_from_id")}),
    )
    list_display = DjangoUserAdmin.list_display + ("full_name", "telegram_chat_id", "telegram_from_id")

