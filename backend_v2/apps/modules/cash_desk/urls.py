from django.urls import path

from apps.modules.cash_desk.views import CashDeskConfigView, CashTransferTargetView

urlpatterns = [
    path("config/", CashDeskConfigView.as_view(), name="cash-desk-config"),
    path("transfers/<int:request_id>/target/", CashTransferTargetView.as_view(), name="cash-desk-transfer-target"),
]
