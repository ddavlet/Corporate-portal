"""
Investments part of `clone_tenant_config` (see apps.tenants.config_clone): the
form config, payout approval chains (per return type / recipient), the project
investment approval chain and payout notifications. Companies, investments and
payouts are tenant data and are not copied.
"""

from __future__ import annotations

from apps.modules.investments.models import (
    InvestmentApprovalConfig,
    InvestmentApprovalConfigStep,
    InvestmentApprovalConfigStepApprover,
    InvestmentFormConfig,
    InvestmentProjectApprovalConfig,
    InvestmentProjectApprovalConfigStep,
    InvestmentProjectApprovalConfigStepApprover,
    InvestNotificationConfig,
)


def _label(config) -> str:
    return f"{config.return_type or 'все типы'} / {config.recipient or 'все получатели'}"


def _clone_steps(ctx, *, src_config, dst_config, step_model, approver_model, member_ids: set[int], where: str) -> None:
    existing = set(dst_config.steps.values_list("step", flat=True))
    for src_step in src_config.steps.all().order_by("step"):
        if src_step.step in existing:
            continue
        approver_ids = list(src_step.step_approvers.order_by("id").values_list("approver_user_id", flat=True))
        kept = [uid for uid in approver_ids if uid in member_ids]
        dst_step = step_model.objects.create(
            config=dst_config,
            step=src_step.step,
            step_type=src_step.step_type,
            is_enabled=src_step.is_enabled and bool(kept),
            telegram_chat=ctx.chat(src_step.telegram_chat),
        )
        approver_model.objects.bulk_create([approver_model(step=dst_step, approver_user_id=uid) for uid in kept])
        ctx.change(f"{where}: шаг {src_step.step} ({src_step.step_type}) добавлен, согласующих: {len(kept)}.")
        if src_step.is_enabled and not kept:
            ctx.warn(f"{where}: шаг {src_step.step} создан выключенным — нет согласующих среди участников тенанта.")


def clone(ctx) -> None:
    member_ids = ctx.target_member_ids()

    src_form = InvestmentFormConfig.objects.filter(tenant=ctx.source).first()
    if src_form is not None and not InvestmentFormConfig.objects.filter(tenant=ctx.target).exists():
        InvestmentFormConfig.objects.create(
            tenant=ctx.target, uses_companies=src_form.uses_companies, allowed_return_types=src_form.allowed_return_types,
        )
        ctx.change("Инвестиции: настройки формы скопированы.")

    target_configs = {
        (c.return_type, c.recipient): c for c in InvestmentApprovalConfig.objects.filter(tenant=ctx.target)
    }
    for src in InvestmentApprovalConfig.objects.filter(tenant=ctx.source).order_by("id"):
        where = f"Инвестиции, согласование выплат ({_label(src)})"
        dst = target_configs.get((src.return_type, src.recipient))
        if dst is None:
            dst = InvestmentApprovalConfig.objects.create(
                tenant=ctx.target, return_type=src.return_type, recipient=src.recipient, is_enabled=src.is_enabled,
            )
            ctx.change(f"{where}: добавлено.")
        _clone_steps(
            ctx, src_config=src, dst_config=dst, step_model=InvestmentApprovalConfigStep,
            approver_model=InvestmentApprovalConfigStepApprover, member_ids=member_ids, where=where,
        )

    src_project = InvestmentProjectApprovalConfig.objects.filter(tenant=ctx.source).first()
    if src_project is not None:
        dst_project, created = InvestmentProjectApprovalConfig.objects.get_or_create(
            tenant=ctx.target, defaults={"is_enabled": src_project.is_enabled},
        )
        if created:
            ctx.change("Инвестиции: согласование вложений добавлено.")
        _clone_steps(
            ctx, src_config=src_project, dst_config=dst_project, step_model=InvestmentProjectApprovalConfigStep,
            approver_model=InvestmentProjectApprovalConfigStepApprover, member_ids=member_ids,
            where="Инвестиции, согласование вложений",
        )

    src_notify = InvestNotificationConfig.objects.filter(tenant=ctx.source).first()
    if src_notify is not None and not InvestNotificationConfig.objects.filter(tenant=ctx.target).exists():
        if src_notify.responsible_user_id not in member_ids:
            ctx.warn("Инвестиции: уведомления о выплатах не скопированы — ответственный не участник тенанта.")
        else:
            InvestNotificationConfig.objects.create(
                tenant=ctx.target,
                responsible_user_id=src_notify.responsible_user_id,
                days_before=src_notify.days_before,
                overdue_notify_every_days=src_notify.overdue_notify_every_days,
                notify_hour=src_notify.notify_hour,
                telegram_chat=ctx.chat(src_notify.telegram_chat),
                is_active=src_notify.is_active,
            )
            ctx.change("Инвестиции: уведомления о выплатах скопированы.")
