from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.vendors.views import VendorViewSet

router = DefaultRouter()
router.register(r"", VendorViewSet, basename="vendors")

urlpatterns = [
    path("", include(router.urls)),
]
