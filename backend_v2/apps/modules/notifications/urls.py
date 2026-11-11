from django.urls import path

from apps.modules.notifications.views import ActionItemsView, AllActionItemsView


urlpatterns = [
    path("action-items/", ActionItemsView.as_view(), name="notifications-action-items"),
    path("action-items/all/", AllActionItemsView.as_view(), name="notifications-action-items-all"),
]
