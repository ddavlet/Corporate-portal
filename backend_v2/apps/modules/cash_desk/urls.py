from django.urls import path

from apps.modules.cash_desk.card_topup_views import CardTopupNotifyConfigView
from apps.modules.cash_desk.views import CashDeskConfigView, CashTransferTargetView

urlpatterns = [
    path("config/", CashDeskConfigView.as_view(), name="cash-desk-config"),
    path("card-topup/config/", CardTopupNotifyConfigView.as_view(), name="cash-desk-card-topup-config"),
    path("transfers/<int:request_id>/target/", CashTransferTargetView.as_view(), name="cash-desk-transfer-target"),
]
