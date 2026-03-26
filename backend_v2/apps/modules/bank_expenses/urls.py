from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.modules.bank_expenses.views import BankExpenseViewSet, BankRevenueViewSet


router = DefaultRouter()
router.register(r"expenses", BankExpenseViewSet, basename="bank-expenses")
router.register(r"revenues", BankRevenueViewSet, basename="bank-revenues")

urlpatterns = [
    path("", include(router.urls)),
]

