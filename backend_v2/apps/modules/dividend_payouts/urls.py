from django.urls import path

from apps.modules.dividend_payouts.views import (
    DividendPayoutOptionsView,
    DividendPayoutRuleDetailView,
    DividendPayoutRuleListView,
)

urlpatterns = [
    path("rules/", DividendPayoutRuleListView.as_view(), name="dividend-payouts-rules"),
    path("rules/<int:rule_id>/", DividendPayoutRuleDetailView.as_view(), name="dividend-payouts-rule-detail"),
    path("options/", DividendPayoutOptionsView.as_view(), name="dividend-payouts-options"),
]
