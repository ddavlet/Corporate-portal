from django.urls import path

from apps.modules.notifications.views import (
    ActionItemsView,
    AllActionItemsView,
    PushSubscribeView,
    PushUnsubscribeView,
    PushVapidPublicKeyView,
)


urlpatterns = [
    path("action-items/", ActionItemsView.as_view(), name="notifications-action-items"),
    path("action-items/all/", AllActionItemsView.as_view(), name="notifications-action-items-all"),
    path("push/vapid-public-key/", PushVapidPublicKeyView.as_view(), name="notifications-push-vapid-public-key"),
    path("push/subscribe/", PushSubscribeView.as_view(), name="notifications-push-subscribe"),
    path("push/unsubscribe/", PushUnsubscribeView.as_view(), name="notifications-push-unsubscribe"),
]
