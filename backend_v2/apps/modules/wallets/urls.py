from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.wallets.views import CashRegisterViewSet, WalletViewSet

router = DefaultRouter()
router.register(r"cash-registers", CashRegisterViewSet, basename="wallets-cash-registers")
router.register(r"wallets", WalletViewSet, basename="wallets-wallets")

urlpatterns = [
    path("", include(router.urls)),
]
