from django.urls import path

from apps.modules.reports.views import CashflowReportView, PnlReportView

urlpatterns = [
    path("pnl/", PnlReportView.as_view(), name="reports-pnl"),
    path("cashflow/", CashflowReportView.as_view(), name="reports-cashflow"),
]
