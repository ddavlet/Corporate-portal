from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.investments.views import InvestReturnViewSet


router = DefaultRouter()
router.register(r"returns", InvestReturnViewSet, basename="invest-returns")

urlpatterns = [
    path("", include(router.urls)),
]
