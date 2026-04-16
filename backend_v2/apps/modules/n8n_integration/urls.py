
from django.urls import path

from apps.modules.n8n_integration import views

urlpatterns = [
    path("ai-questions/chat/", views.AiChatProxyView.as_view(), name="n8n-ai-questions-chat"),
    path("pnl-data/", views.N8nPnlDataView.as_view(), name="n8n-pnl-data"),
    path("cashflow-data/", views.N8nCashflowDataView.as_view(), name="n8n-cashflow-data"),
    path("requests/", views.N8nRequestUpsertView.as_view(), name="n8n-requests-upsert"),
    path("requests/amortization/", views.N8nRequestAmortizationView.as_view(), name="n8n-requests-amortization"),
    path("requests/batch/", views.N8nRequestBatchUpsertView.as_view(), name="n8n-requests-batch-upsert"),
    path("approvals/", views.N8nApprovalUpsertView.as_view(), name="n8n-approvals-upsert"),
    path("approvals/batch/", views.N8nApprovalBatchUpsertView.as_view(), name="n8n-approvals-batch-upsert"),
    path("vendors/", views.N8nVendorUpsertView.as_view(), name="n8n-vendors-upsert"),
    path("vendors/batch/", views.N8nVendorBatchUpsertView.as_view(), name="n8n-vendors-batch-upsert"),
    path("cash/expenses/", views.N8nCashExpenseUpsertView.as_view(), name="n8n-cash-expenses-upsert"),
    path("cash/expenses/batch/", views.N8nCashExpenseBatchUpsertView.as_view(), name="n8n-cash-expenses-batch-upsert"),
    path("cash/revenues/", views.N8nCashRevenueUpsertView.as_view(), name="n8n-cash-revenues-upsert"),
    path("cash/revenues/batch/", views.N8nCashRevenueBatchUpsertView.as_view(), name="n8n-cash-revenues-batch-upsert"),
    path("bank/expenses/", views.N8nBankExpenseUpsertView.as_view(), name="n8n-bank-expenses-upsert"),
    path("bank/expenses/batch/", views.N8nBankExpenseBatchUpsertView.as_view(), name="n8n-bank-expenses-batch-upsert"),
    path("bank/revenues/", views.N8nBankRevenueUpsertView.as_view(), name="n8n-bank-revenues-upsert"),
    path("bank/revenues/batch/", views.N8nBankRevenueBatchUpsertView.as_view(), name="n8n-bank-revenues-batch-upsert"),
    path("corporate-card/expenses/", views.N8nCardExpenseUpsertView.as_view(), name="n8n-card-expenses-upsert"),
    path("corporate-card/expenses/batch/", views.N8nCardExpenseBatchUpsertView.as_view(), name="n8n-card-expenses-batch-upsert"),
    path("corporate-card/revenues/", views.N8nCardRevenueUpsertView.as_view(), name="n8n-card-revenues-upsert"),
    path("corporate-card/revenues/batch/", views.N8nCardRevenueBatchUpsertView.as_view(), name="n8n-card-revenues-batch-upsert"),
    path("clients-debt/", views.N8nClientsDebtUpsertView.as_view(), name="n8n-clients-debt-upsert"),
    path("clients-debt/batch/", views.N8nClientsDebtBatchUpsertView.as_view(), name="n8n-clients-debt-batch-upsert"),
    path("notes/", views.N8nNoteUpsertView.as_view(), name="n8n-notes-upsert"),
    path("notes/batch/", views.N8nNoteBatchUpsertView.as_view(), name="n8n-notes-batch-upsert"),
    path("investments/returns/", views.N8nInvestReturnUpsertView.as_view(), name="n8n-invest-returns-upsert"),
    path(
        "investments/returns/batch/",
        views.N8nInvestReturnBatchUpsertView.as_view(),
        name="n8n-invest-returns-batch-upsert",
    ),
    path("payroll/lines/", views.N8nPayrollLineUpsertView.as_view(), name="n8n-payroll-lines-upsert"),
    path("payroll/lines/batch/", views.N8nPayrollLineBatchUpsertView.as_view(), name="n8n-payroll-lines-batch-upsert"),
]
