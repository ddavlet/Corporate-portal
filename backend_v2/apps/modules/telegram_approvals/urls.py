from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.telegram_approvals.views import (
    TelegramApprovalWebhookView,
    TelegramBotSetupView,
    TelegramEventLogView,
    TenantTelegramChatViewSet,
)

router = DefaultRouter()
router.register(r"chats", TenantTelegramChatViewSet, basename="telegram-chats")

urlpatterns = [
    path("webhook/", TelegramApprovalWebhookView.as_view(), name="telegram-approvals-webhook"),
    path("events/", TelegramEventLogView.as_view(), name="telegram-event-log"),
    path("bot-setup/", TelegramBotSetupView.as_view(), name="telegram-bot-setup"),
    path("", include(router.urls)),
]
