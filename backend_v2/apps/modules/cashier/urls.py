from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.modules.cashier.views import CashExpenseViewSet, CashRevenueViewSet


router = DefaultRouter()
router.register(r"expenses", CashExpenseViewSet, basename="cash-expenses")
router.register(r"revenues", CashRevenueViewSet, basename="cash-revenues")

urlpatterns = [
    path("", include(router.urls)),
]

