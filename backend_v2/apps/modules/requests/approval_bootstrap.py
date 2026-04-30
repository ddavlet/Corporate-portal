"""Create Approval rows from tenant RequestApprovalConfig (portal, auto-requests, submit-for-approval)."""

from __future__ import annotations

from apps.modules.requests.approval_config_resolver import resolve_effective_step_configs_for_request
from apps.modules.requests.models import Approval, Request
from apps.tenants.models import TenantMembership


def create_approval_rows_for_request(request_obj: Request) -> int:
    """
    Build and persist Approval rows for request_obj.payment_type.
    Does not recalculate status or dispatch Telegram.
    Returns number of rows created.
    """
    tenant = request_obj.tenant
    step_cfgs = resolve_effective_step_configs_for_request(request_obj)
    if not step_cfgs:
        return 0
    approver_ids: set[int] = set()
    for step_cfg in step_cfgs:
        approver_ids.update(step_cfg.approvers.values_list("approver_user_id", flat=True).distinct())
    active_approver_ids = set(
        TenantMembership.objects.filter(tenant=tenant, is_active=True, user_id__in=approver_ids).values_list(
            "user_id", flat=True
        )
    )
    approval_rows: list[Approval] = []
    for step_cfg in step_cfgs:
        for row in step_cfg.approvers.all():
            if row.approver_user_id not in active_approver_ids:
                continue
            approval_rows.append(
                Approval(
                    request=request_obj,
                    approver_user=row.approver_user,
                    approver_recipient_id=row.approver_user.telegram_chat_id,
                    approver_user_id=row.approver_user.telegram_from_id,
                    gateway_message_id=None,
                    message_sent=False,
                    step=step_cfg.step,
                    step_type=step_cfg.step_type,
                    decision=Approval.DECISION_PENDING,
                    comment=None,
                    decided_at=None,
                )
            )
    if not approval_rows:
        return 0
    Approval.objects.bulk_create(approval_rows)
    return len(approval_rows)
