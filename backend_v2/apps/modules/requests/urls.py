from django.urls import path, include
from rest_framework.routers import DefaultRouter

from apps.modules.requests.views import (
    PortalRequestViewSet,
    RequestFormConfigView,
    RequestFormConfigRequestersView,
    RequestFormOptionsView,
    RequestApprovalConfigView,
    AutoRequestConfigView,
    RequestAiChatProxyView,
)


router = DefaultRouter()
router.register(r"", PortalRequestViewSet, basename="requests")

urlpatterns = [
    path("ai-chat/", RequestAiChatProxyView.as_view(), name="requests_ai_chat"),
    path("form-config/", RequestFormConfigView.as_view(), name="requests_form_config"),
    path(
        "form-config/requesters/",
        RequestFormConfigRequestersView.as_view(),
        name="requests_form_config_requesters",
    ),
    path("approval-config/", RequestApprovalConfigView.as_view(), name="requests_approval_config"),
    path("auto-config/", AutoRequestConfigView.as_view(), name="requests_auto_config"),
    path("form-options/", RequestFormOptionsView.as_view(), name="requests_form_options"),
    path("", include(router.urls)),
]

