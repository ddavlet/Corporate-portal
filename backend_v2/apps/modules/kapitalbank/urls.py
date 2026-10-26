from django.urls import path

from apps.modules.kapitalbank.views import PendingAccountsView

urlpatterns = [
    path("pending-accounts/", PendingAccountsView.as_view(), name="kapitalbank-pending-accounts"),
]
