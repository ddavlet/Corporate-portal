from django.urls import path

from apps.modules.cash_withdrawals.views import CashWithdrawalConfigView

urlpatterns = [
    path("config/", CashWithdrawalConfigView.as_view(), name="cash-withdrawals-config"),
]
