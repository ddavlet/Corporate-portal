from django.urls import path

from apps.modules.reports.views import (
    CashflowReportView,
    PnlReportView,
    TenantCashflowReportSettingsConfigView,
    TenantPnlPaymentPurposePoolView,
    TenantReportSettingsConfigView,
)

urlpatterns = [
    path("pnl/", PnlReportView.as_view(), name="reports-pnl"),
    path("cashflow/", CashflowReportView.as_view(), name="reports-cashflow"),
    path("tenant-report-settings/", TenantReportSettingsConfigView.as_view(), name="reports-tenant-report-settings"),
    path(
        "cashflow-report-settings/",
        TenantCashflowReportSettingsConfigView.as_view(),
        name="reports-cashflow-report-settings",
    ),
    path(
        "payment-purpose-pool/",
        TenantPnlPaymentPurposePoolView.as_view(),
        name="reports-payment-purpose-pool",
    ),
]
