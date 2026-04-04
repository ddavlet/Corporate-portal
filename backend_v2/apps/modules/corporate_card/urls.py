from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.corporate_card.views import (
    CardExpenseViewSet,
    CardRevenueViewSet,
    CorporateCardBalancesView,
)


router = DefaultRouter()
router.register(r"expenses", CardExpenseViewSet, basename="corporate-card-expenses")
router.register(r"revenues", CardRevenueViewSet, basename="corporate-card-revenues")

urlpatterns = [
    path("balances/", CorporateCardBalancesView.as_view(), name="corporate-card-balances"),
    path("", include(router.urls)),
]

