from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.investments.views import (
    InvestCompanyViewSet,
    InvestPayoutScheduleViewSet,
    InvestReturnViewSet,
    ProjectInvestmentViewSet,
)


router = DefaultRouter()
router.register(r"companies", InvestCompanyViewSet, basename="invest-companies")
router.register(r"returns", InvestReturnViewSet, basename="invest-returns")
router.register(r"payout-schedule", InvestPayoutScheduleViewSet, basename="invest-payout-schedule")
router.register(r"project-investments", ProjectInvestmentViewSet, basename="project-investments")

urlpatterns = [
    path("", include(router.urls)),
]
