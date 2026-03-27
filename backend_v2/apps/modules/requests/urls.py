from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.modules.requests.views import PortalRequestViewSet, RequestFormConfigView, RequestFormOptionsView


router = DefaultRouter()
router.register(r"", PortalRequestViewSet, basename="requests")

urlpatterns = [
    path("form-config/", RequestFormConfigView.as_view(), name="requests_form_config"),
    path("form-options/", RequestFormOptionsView.as_view(), name="requests_form_options"),
    path("", include(router.urls)),
]

