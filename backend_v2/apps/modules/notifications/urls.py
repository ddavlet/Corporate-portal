from django.urls import path

from apps.modules.notifications.views import ActionItemsView


urlpatterns = [
    path("action-items/", ActionItemsView.as_view(), name="notifications-action-items"),
]
