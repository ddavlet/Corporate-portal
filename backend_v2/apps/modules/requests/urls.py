from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.modules.requests.views import PortalRequestViewSet


router = DefaultRouter()
router.register(r"", PortalRequestViewSet, basename="requests")

urlpatterns = [
    path("", include(router.urls)),
]

