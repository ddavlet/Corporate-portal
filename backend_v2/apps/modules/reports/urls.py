from django.urls import path

from apps.modules.reports.views import (
    CashflowReportView,
    PnlReportView,
    ReportTemplatesView,
    StatementExportView,
    StatementLinesExportView,
    StatementLinesView,
    StatementView,
    TenantCashflowReportSettingsConfigView,
    TenantPnlPaymentPurposePoolView,
    TenantReportSettingsConfigView,
)

urlpatterns = [
    path("pnl/", PnlReportView.as_view(), name="reports-pnl"),
    path("cashflow/", CashflowReportView.as_view(), name="reports-cashflow"),
    path("templates/", ReportTemplatesView.as_view(), name="reports-templates"),
    path("statement/", StatementView.as_view(), name="reports-statement"),
    path("statement/lines/", StatementLinesView.as_view(), name="reports-statement-lines"),
    path("statement/export/", StatementExportView.as_view(), name="reports-statement-export"),
    path("statement/lines/export/", StatementLinesExportView.as_view(), name="reports-statement-lines-export"),
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
