from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.payroll.views import (
    CashExpensePayrollPayoutsView,
    EmployeeCreateView,
    EmployeeListView,
    PayablePayrollDocumentsView,
    PayrollBankEmployeeLinkCreateView,
    PayrollCardAttentionView,
    PayrollCardPayoutAssignView,
    PayrollCloseUnderpaidView,
    PayrollDocumentCreateView,
    PayrollDocumentViewSet,
    PayrollExpectedCardView,
    PayrollPayoutCreateView,
    PayrollPayoutStateView,
)

router = DefaultRouter()
router.register(r"documents", PayrollDocumentViewSet, basename="payroll-documents")

urlpatterns = [
    path("documents/create/", PayrollDocumentCreateView.as_view(), name="payroll-documents-create"),
    path("documents/<int:pk>/payout-state/", PayrollPayoutStateView.as_view(), name="payroll-payout-state"),
    path("documents/<int:pk>/payouts/", PayrollPayoutCreateView.as_view(), name="payroll-payouts-create"),
    path("documents/<int:pk>/close-underpaid/", PayrollCloseUnderpaidView.as_view(), name="payroll-close-underpaid"),
    path("payable-documents/", PayablePayrollDocumentsView.as_view(), name="payroll-payable-documents"),
    path("cash-expenses/<int:pk>/payouts/", CashExpensePayrollPayoutsView.as_view(), name="payroll-cash-expense-payouts"),
    path("employees/", EmployeeListView.as_view(), name="payroll-employees"),
    path("employees/create/", EmployeeCreateView.as_view(), name="payroll-employees-create"),
    path("card-payouts/attention/", PayrollCardAttentionView.as_view(), name="payroll-card-attention"),
    path("card-payouts/<int:pk>/assign/", PayrollCardPayoutAssignView.as_view(), name="payroll-card-payout-assign"),
    path("bank-employee-links/", PayrollBankEmployeeLinkCreateView.as_view(), name="payroll-bank-employee-links"),
    path(
        "documents/<int:pk>/expected-card/", PayrollExpectedCardView.as_view(), name="payroll-document-expected-card"
    ),
    path("", include(router.urls)),
]
