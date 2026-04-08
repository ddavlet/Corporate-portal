
from django.urls import path

from apps.modules.n8n_integration import views

urlpatterns = [
    path("requests/", views.N8nRequestUpsertView.as_view(), name="n8n-requests-upsert"),
    path("approvals/", views.N8nApprovalUpsertView.as_view(), name="n8n-approvals-upsert"),
    path("vendors/", views.N8nVendorUpsertView.as_view(), name="n8n-vendors-upsert"),
    path("cash/expenses/", views.N8nCashExpenseUpsertView.as_view(), name="n8n-cash-expenses-upsert"),
    path("cash/revenues/", views.N8nCashRevenueUpsertView.as_view(), name="n8n-cash-revenues-upsert"),
    path("bank/expenses/", views.N8nBankExpenseUpsertView.as_view(), name="n8n-bank-expenses-upsert"),
    path("bank/revenues/", views.N8nBankRevenueUpsertView.as_view(), name="n8n-bank-revenues-upsert"),
    path("corporate-card/expenses/", views.N8nCardExpenseUpsertView.as_view(), name="n8n-card-expenses-upsert"),
    path("corporate-card/revenues/", views.N8nCardRevenueUpsertView.as_view(), name="n8n-card-revenues-upsert"),
    path("notes/", views.N8nNoteUpsertView.as_view(), name="n8n-notes-upsert"),
    path("payroll/lines/", views.N8nPayrollLineUpsertView.as_view(), name="n8n-payroll-lines-upsert"),
]
