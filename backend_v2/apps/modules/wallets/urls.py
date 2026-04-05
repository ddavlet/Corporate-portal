from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.wallets.views import (
    BankAccountViewSet,
    CashRegisterViewSet,
    CorporateCardAccountViewSet,
    WalletViewSet,
)

router = DefaultRouter()
router.register(r"cash-registers", CashRegisterViewSet, basename="wallets-cash-registers")
router.register(r"bank-accounts", BankAccountViewSet, basename="wallets-bank-accounts")
router.register(
    r"corporate-card-accounts",
    CorporateCardAccountViewSet,
    basename="wallets-corporate-card-accounts",
)
router.register(r"wallets", WalletViewSet, basename="wallets-wallets")

urlpatterns = [
    path("", include(router.urls)),
]
