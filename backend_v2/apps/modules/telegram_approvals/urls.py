from django.urls import path

from apps.modules.telegram_approvals.views import TelegramApprovalWebhookView


urlpatterns = [
    path("webhook/", TelegramApprovalWebhookView.as_view(), name="telegram-approvals-webhook"),
]

