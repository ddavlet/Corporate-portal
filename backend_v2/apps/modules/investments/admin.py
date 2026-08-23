from django.contrib import admin

from apps.modules.investments.models import CbuExchangeRate


@admin.register(CbuExchangeRate)
class CbuExchangeRateAdmin(admin.ModelAdmin):
    list_display = ["date", "usd_uzs_rate", "updated_at"]
    ordering = ["-date"]
