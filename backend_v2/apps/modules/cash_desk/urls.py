from django.urls import path

from apps.modules.cash_desk.views import CashDeskConfigView

urlpatterns = [
    path("config/", CashDeskConfigView.as_view(), name="cash-desk-config"),
]
