from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.payroll.views import (
    CashExpensePayrollPayoutsView,
    EmployeeCreateView,
    EmployeeListView,
    PayablePayrollDocumentsView,
    PayrollCloseUnderpaidView,
    PayrollDocumentCreateView,
    PayrollDocumentViewSet,
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
    path("", include(router.urls)),
]
