"""Send an approver on vacation / bring them back.

While a user is "on vacation", their mandatory (`serial`) approval steps for
a tenant are switched to `notification` so requests aren't stuck waiting on
someone who's away. Steps that were already `notification` for that user are
left untouched, and `payment` steps (actual payment execution) are never
touched — someone still has to make the payment.

`UserApprovalVacation.snapshot` records exactly which step configs were
flipped, so `end_vacation` restores exactly those and only those.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.modules.requests.models import (
    Approval,
    RequestApprovalConfig,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalStepConfig,
    UserApprovalVacation,
)


class VacationAlreadyActive(Exception):
    pass


class NoActiveVacation(Exception):
    pass


@dataclass(frozen=True)
class StepRef:
    kind: str
    id: int
    payment_type: str
    label: str


@dataclass
class VacationStartPlan:
    to_notify: list[StepRef] = field(default_factory=list)
    already_notification: list[StepRef] = field(default_factory=list)
    skipped_payment: list[StepRef] = field(default_factory=list)


@dataclass
class VacationEndResult:
    restored: list[StepRef] = field(default_factory=list)
    skipped_changed: list[StepRef] = field(default_factory=list)


def _regular_step_configs_for_user(appr_cfg: RequestApprovalConfig, user):
    return list(
        RequestApprovalStepConfig.objects.filter(
            payment_type_config__config=appr_cfg,
            approvers__approver_user=user,
        )
        .select_related("payment_type_config")
        .distinct()
        .order_by("id")
    )


def _exception_step_configs_for_user(appr_cfg: RequestApprovalConfig, user):
    return list(
        RequestApprovalPurposeExceptionStepConfig.objects.filter(
            exception_config__payment_type_config__config=appr_cfg,
            approvers__approver_user=user,
        )
        .select_related("exception_config__payment_type_config", "exception_config")
        .distinct()
        .order_by("id")
    )


def _regular_ref(step_cfg: RequestApprovalStepConfig) -> StepRef:
    return StepRef(
        kind=UserApprovalVacation.KIND_STEP,
        id=step_cfg.id,
        payment_type=step_cfg.payment_type_config.payment_type,
        label=f"{step_cfg.payment_type_config.payment_type} / шаг {step_cfg.step}",
    )


def _exception_ref(step_cfg: RequestApprovalPurposeExceptionStepConfig) -> StepRef:
    exc = step_cfg.exception_config
    return StepRef(
        kind=UserApprovalVacation.KIND_EXCEPTION_STEP,
        id=step_cfg.id,
        payment_type=exc.payment_type_config.payment_type,
        label=f"{exc.payment_type_config.payment_type} / исключение '{exc.name or exc.pk}' / шаг {step_cfg.step}",
    )


def plan_vacation_start(*, tenant, user) -> VacationStartPlan:
    plan = VacationStartPlan()
    appr_cfg = RequestApprovalConfig.objects.filter(tenant=tenant).first()
    if appr_cfg is None:
        return plan

    for step_cfg in _regular_step_configs_for_user(appr_cfg, user):
        _bucket_for(plan, step_cfg.step_type).append(_regular_ref(step_cfg))
    for step_cfg in _exception_step_configs_for_user(appr_cfg, user):
        _bucket_for(plan, step_cfg.step_type).append(_exception_ref(step_cfg))
    return plan


def _bucket_for(plan: VacationStartPlan, step_type: str) -> list[StepRef]:
    if step_type == Approval.STEP_TYPE_SERIAL:
        return plan.to_notify
    if step_type == Approval.STEP_TYPE_NOTIFICATION:
        return plan.already_notification
    return plan.skipped_payment


@transaction.atomic
def start_vacation(*, tenant, user) -> tuple[UserApprovalVacation, VacationStartPlan]:
    if UserApprovalVacation.objects.select_for_update().filter(
        tenant=tenant, user=user, ended_at__isnull=True
    ).exists():
        raise VacationAlreadyActive(f"У пользователя {user} уже есть активный отпуск в тенанте {tenant}.")

    plan = plan_vacation_start(tenant=tenant, user=user)

    step_ids = [ref.id for ref in plan.to_notify if ref.kind == UserApprovalVacation.KIND_STEP]
    exception_ids = [ref.id for ref in plan.to_notify if ref.kind == UserApprovalVacation.KIND_EXCEPTION_STEP]
    RequestApprovalStepConfig.objects.filter(id__in=step_ids).update(step_type=Approval.STEP_TYPE_NOTIFICATION)
    RequestApprovalPurposeExceptionStepConfig.objects.filter(id__in=exception_ids).update(
        step_type=Approval.STEP_TYPE_NOTIFICATION
    )

    vacation = UserApprovalVacation.objects.create(
        tenant=tenant,
        user=user,
        snapshot=[{"kind": ref.kind, "id": ref.id} for ref in plan.to_notify],
    )
    return vacation, plan


@transaction.atomic
def end_vacation(*, tenant, user) -> tuple[UserApprovalVacation, VacationEndResult]:
    vacation = (
        UserApprovalVacation.objects.select_for_update()
        .filter(tenant=tenant, user=user, ended_at__isnull=True)
        .first()
    )
    if vacation is None:
        raise NoActiveVacation(f"Нет активного отпуска для пользователя {user} в тенанте {tenant}.")

    step_ids = [entry["id"] for entry in vacation.snapshot if entry["kind"] == UserApprovalVacation.KIND_STEP]
    exception_ids = [
        entry["id"] for entry in vacation.snapshot if entry["kind"] == UserApprovalVacation.KIND_EXCEPTION_STEP
    ]
    step_cfgs = {
        sc.id: sc
        for sc in RequestApprovalStepConfig.objects.filter(id__in=step_ids).select_related("payment_type_config")
    }
    exception_cfgs = {
        sc.id: sc
        for sc in RequestApprovalPurposeExceptionStepConfig.objects.filter(id__in=exception_ids).select_related(
            "exception_config__payment_type_config"
        )
    }

    result = VacationEndResult()
    restore_step_ids: list[int] = []
    restore_exception_ids: list[int] = []
    for entry in vacation.snapshot:
        cfg = step_cfgs.get(entry["id"]) if entry["kind"] == UserApprovalVacation.KIND_STEP else exception_cfgs.get(
            entry["id"]
        )
        if cfg is None:
            # Config was deleted while the user was on vacation — nothing to restore.
            continue
        ref = _regular_ref(cfg) if entry["kind"] == UserApprovalVacation.KIND_STEP else _exception_ref(cfg)
        if cfg.step_type == Approval.STEP_TYPE_NOTIFICATION:
            result.restored.append(ref)
            (restore_step_ids if entry["kind"] == UserApprovalVacation.KIND_STEP else restore_exception_ids).append(
                entry["id"]
            )
        else:
            # Someone changed it manually during the vacation — don't clobber that.
            result.skipped_changed.append(ref)

    RequestApprovalStepConfig.objects.filter(id__in=restore_step_ids).update(step_type=Approval.STEP_TYPE_SERIAL)
    RequestApprovalPurposeExceptionStepConfig.objects.filter(id__in=restore_exception_ids).update(
        step_type=Approval.STEP_TYPE_SERIAL
    )

    vacation.ended_at = timezone.now()
    vacation.save(update_fields=["ended_at"])
    return vacation, result
