from django.urls import path

from apps.modules.kapitalbank.views import PendingAccountsView, UntrackedAccountsView

urlpatterns = [
    path("pending-accounts/", PendingAccountsView.as_view(), name="kapitalbank-pending-accounts"),
    path("untracked-accounts/", UntrackedAccountsView.as_view(), name="kapitalbank-untracked-accounts"),
]
