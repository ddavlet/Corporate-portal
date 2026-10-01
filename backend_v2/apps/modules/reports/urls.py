from django.urls import path

from apps.modules.reports.views import (
    CashflowReportView,
    PnlReportView,
    ReportRulesView,
    ReportTemplatesView,
    StatementExportView,
    StatementLinesExportView,
    StatementLinesView,
    StatementVendorsView,
    StatementView,
    TenantPnlPaymentPurposePoolView,
)

urlpatterns = [
    path("pnl/", PnlReportView.as_view(), name="reports-pnl"),
    path("cashflow/", CashflowReportView.as_view(), name="reports-cashflow"),
    path("templates/", ReportTemplatesView.as_view(), name="reports-templates"),
    path("rules/<str:report>/", ReportRulesView.as_view(), name="reports-rules"),
    path("statement/", StatementView.as_view(), name="reports-statement"),
    path("statement/lines/", StatementLinesView.as_view(), name="reports-statement-lines"),
    path("statement/vendors/", StatementVendorsView.as_view(), name="reports-statement-vendors"),
    path("statement/export/", StatementExportView.as_view(), name="reports-statement-export"),
    path("statement/lines/export/", StatementLinesExportView.as_view(), name="reports-statement-lines-export"),
    path(
        "payment-purpose-pool/",
        TenantPnlPaymentPurposePoolView.as_view(),
        name="reports-payment-purpose-pool",
    ),
]
