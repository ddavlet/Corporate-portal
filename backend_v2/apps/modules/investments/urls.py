from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.investments.views import (
    InvestCompanyViewSet,
    InvestmentApprovalConfigReadViewSet,
    InvestmentApprovalConfigStepApproverReadViewSet,
    InvestmentApprovalConfigStepReadViewSet,
    InvestmentApprovalConfigView,
    InvestmentApprovalDecisionView,
    InvestmentApprovalWebhookView,
    InvestmentFormConfigReadViewSet,
    InvestmentFormConfigView,
    InvestmentProjectApprovalConfigReadViewSet,
    InvestmentProjectApprovalConfigStepApproverReadViewSet,
    InvestmentProjectApprovalConfigStepReadViewSet,
    InvestmentProjectApprovalConfigView,
    InvestmentProjectApprovalDecisionView,
    InvestmentReturnApprovalReadViewSet,
    InvestNotificationConfigView,
    InvestPayoutScheduleViewSet,
    InvestPayoutScheduleShareLinkViewSet,
    InvestReturnViewSet,
    ProjectInvestmentApprovalReadViewSet,
    PublicInvestPayoutScheduleByTokenView,
    ProjectInvestmentViewSet,
)


router = DefaultRouter()
router.register(r"companies", InvestCompanyViewSet, basename="invest-companies")
router.register(r"returns", InvestReturnViewSet, basename="invest-returns")
router.register(r"payout-schedule", InvestPayoutScheduleViewSet, basename="invest-payout-schedule")
router.register(r"payout-schedule-share-links", InvestPayoutScheduleShareLinkViewSet, basename="invest-payout-schedule-share-links")
router.register(r"project-investments", ProjectInvestmentViewSet, basename="project-investments")
router.register(r"form-config-records", InvestmentFormConfigReadViewSet, basename="invest-form-config-records")
router.register(r"approval-configs", InvestmentApprovalConfigReadViewSet, basename="invest-approval-configs")
router.register(r"approval-config-steps", InvestmentApprovalConfigStepReadViewSet, basename="invest-approval-config-steps")
router.register(
    r"approval-config-step-approvers",
    InvestmentApprovalConfigStepApproverReadViewSet,
    basename="invest-approval-config-step-approvers",
)
router.register(r"return-approvals", InvestmentReturnApprovalReadViewSet, basename="invest-return-approvals")
router.register(
    r"project-approval-configs",
    InvestmentProjectApprovalConfigReadViewSet,
    basename="invest-project-approval-configs",
)
router.register(
    r"project-approval-config-steps",
    InvestmentProjectApprovalConfigStepReadViewSet,
    basename="invest-project-approval-config-steps",
)
router.register(
    r"project-approval-config-step-approvers",
    InvestmentProjectApprovalConfigStepApproverReadViewSet,
    basename="invest-project-approval-config-step-approvers",
)
router.register(
    r"project-investment-approvals",
    ProjectInvestmentApprovalReadViewSet,
    basename="invest-project-investment-approvals",
)

urlpatterns = [
    path("", include(router.urls)),
    path("public/payout-schedule/<str:token>/", PublicInvestPayoutScheduleByTokenView.as_view(), name="invest-public-payout-schedule"),
    path("form-config/", InvestmentFormConfigView.as_view(), name="invest-form-config"),
    path("notification-config/", InvestNotificationConfigView.as_view(), name="invest-notification-config"),
    path("approval-config/", InvestmentApprovalConfigView.as_view(), name="invest-approval-config"),
    path("project-approval-config/", InvestmentProjectApprovalConfigView.as_view(), name="invest-project-approval-config"),
    path("approvals/<int:approval_id>/decision/", InvestmentApprovalDecisionView.as_view(), name="invest-approval-decision"),
    path(
        "project-approvals/<int:approval_id>/decision/",
        InvestmentProjectApprovalDecisionView.as_view(),
        name="invest-project-approval-decision",
    ),
    path("approvals/webhook/", InvestmentApprovalWebhookView.as_view(), name="invest-approvals-webhook"),
]
