from __future__ import annotations

from dataclasses import dataclass

from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalStepConfig,
)


@dataclass(frozen=True)
class EffectivePaymentStepConfig:
    payment_action_mode: str
    payment_webapp_url: str
    payment_chat_id: int | None


def _resolve_payment_type_config_for_request(request_obj: Request):
    cfg = RequestApprovalConfig.objects.filter(tenant=request_obj.tenant).first()
    if not cfg:
        return None
    return cfg.payment_types.filter(payment_type=request_obj.payment_type, is_enabled=True).first()


def _resolve_matching_exception(*, pt_cfg, payment_purpose: str):
    purpose_value = str(payment_purpose or "").strip()
    if not purpose_value:
        return None
    return (
        RequestApprovalPurposeExceptionConfig.objects.filter(
            payment_type_config=pt_cfg,
            is_enabled=True,
            purposes__payment_purpose__name=purpose_value,
        )
        .order_by("id")
        .first()
    )


def resolve_effective_step_configs_for_request(request_obj: Request):
    pt_cfg = _resolve_payment_type_config_for_request(request_obj)
    if not pt_cfg:
        return []
    matched_exception = _resolve_matching_exception(
        pt_cfg=pt_cfg,
        payment_purpose=request_obj.payment_purpose,
    )
    if matched_exception:
        return list(
            RequestApprovalPurposeExceptionStepConfig.objects.filter(
                exception_config=matched_exception,
                is_enabled=True,
            )
            .order_by("step", "id")
            .prefetch_related("approvers__approver_user")
        )
    return list(
        pt_cfg.steps.filter(is_enabled=True)
        .order_by("step", "id")
        .prefetch_related("approvers__approver_user")
    )


def resolve_effective_payment_step_config_for_request(
    *,
    request_obj: Request,
    step: int,
    step_type: str,
) -> EffectivePaymentStepConfig | None:
    if step_type != Approval.STEP_TYPE_PAYMENT:
        return None
    for step_cfg in resolve_effective_step_configs_for_request(request_obj):
        if int(getattr(step_cfg, "step", 0)) != int(step):
            continue
        if getattr(step_cfg, "step_type", None) != step_type:
            continue
        return EffectivePaymentStepConfig(
            payment_action_mode=getattr(step_cfg, "payment_action_mode", RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CALLBACK),
            payment_webapp_url=getattr(step_cfg, "payment_webapp_url", "") or "",
            payment_chat_id=getattr(step_cfg, "payment_chat_id", None),
        )
    return None
