"""
Requests part of `clone_tenant_config` (see apps.tenants.config_clone): active
categories, the request form (payment types, active purposes, allowed
requesters) and the approval routes with their purpose exceptions.

Vendors are tenant data and are not copied: per-type vendor lists and default
vendors stay empty. A per-type default payer equal to the source tenant name is
replaced by the target tenant name.
"""

from __future__ import annotations

from apps.modules.requests.models import (
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestApprovalPurposeExceptionStepApproverConfig,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestCategory,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestFormPaymentTypeRequester,
    RequestPaymentPurposeConfig,
)

_FORM_DEFAULT_FIELDS = (
    "is_enabled",
    "default_title",
    "default_description",
    "default_amount",
    "default_currency",
    "default_urgency",
    "default_billing_days_offset",
    "default_payment_purpose",
    "contracts_required",
)


def _clone_categories(ctx) -> None:
    existing = set(RequestCategory.objects.filter(tenant=ctx.target).values_list("name", flat=True))
    for category in RequestCategory.objects.filter(tenant=ctx.source, is_active=True).order_by("name"):
        if category.name not in existing:
            RequestCategory.objects.create(tenant=ctx.target, name=category.name, is_active=True)
            ctx.change(f"Категория «{category.name}» добавлена.")


def _company_payer(ctx, value: str) -> str:
    if value and value.strip().casefold() == ctx.source.name.strip().casefold():
        return ctx.target.name
    if value:
        ctx.warn(f"Плательщик по умолчанию «{value}» скопирован как есть — проверьте.")
    return value


def _clone_form(ctx, member_ids: set[int]) -> None:
    source_cfg = RequestFormConfig.objects.filter(tenant=ctx.source).first()
    if source_cfg is None:
        return
    target_cfg, _ = RequestFormConfig.objects.get_or_create(tenant=ctx.target)
    target_types = {p.payment_type: p for p in RequestFormPaymentTypeConfig.objects.filter(config=target_cfg)}

    for src in RequestFormPaymentTypeConfig.objects.filter(config=source_cfg).order_by("id"):
        dst = target_types.get(src.payment_type)
        if dst is None:
            dst = RequestFormPaymentTypeConfig.objects.create(
                config=target_cfg,
                payment_type=src.payment_type,
                default_company_payer=_company_payer(ctx, src.default_company_payer),
                **{name: getattr(src, name) for name in _FORM_DEFAULT_FIELDS},
            )
            ctx.change(f"Форма заявки: тип оплаты «{src.payment_type}» добавлен.")

        existing = set(RequestPaymentPurposeConfig.objects.filter(payment_type_config=dst).values_list("name", flat=True))
        added = [
            RequestPaymentPurposeConfig(payment_type_config=dst, name=p.name, category=p.category, is_active=True)
            for p in RequestPaymentPurposeConfig.objects.filter(payment_type_config=src, is_active=True).order_by("name")
            if p.name not in existing
        ]
        if added:
            RequestPaymentPurposeConfig.objects.bulk_create(added)
            ctx.change(f"Форма заявки: «{src.payment_type}» — назначений добавлено: {len(added)}.")

        allowed = set(RequestFormPaymentTypeRequester.objects.filter(payment_type_config=dst).values_list("user_id", flat=True))
        requester_ids = set(
            RequestFormPaymentTypeRequester.objects.filter(payment_type_config=src).values_list("user_id", flat=True)
        )
        new_ids = sorted((requester_ids & member_ids) - allowed)
        RequestFormPaymentTypeRequester.objects.bulk_create(
            [RequestFormPaymentTypeRequester(payment_type_config=dst, user_id=uid) for uid in new_ids]
        )
        if new_ids:
            ctx.change(f"Форма заявки: «{src.payment_type}» — заявителей добавлено: {len(new_ids)}.")
        if requester_ids - member_ids - allowed:
            ctx.warn(f"Форма заявки: «{src.payment_type}» — {len(requester_ids - member_ids)} заявител(ей) не участники тенанта, не добавлены.")
        if src.default_vendor_id:
            ctx.warn(f"Форма заявки: «{src.payment_type}» — поставщик по умолчанию не копируется.")


def _copy_step(ctx, *, model, approver_model, parent_field: str, parent, src_step, member_ids: set[int], where: str) -> None:
    approver_ids = [a.approver_user_id for a in src_step.approvers.all().order_by("id")]
    kept = [uid for uid in approver_ids if uid in member_ids]
    url = ctx.bot_link(src_step.payment_webapp_url)
    dst_step = model.objects.create(
        **{parent_field: parent},
        step=src_step.step,
        step_type=src_step.step_type,
        is_enabled=src_step.is_enabled and bool(kept),
        payment_action_mode=src_step.payment_action_mode,
        payment_webapp_url=url,
        telegram_chat=ctx.chat(src_step.telegram_chat),
    )
    approver_model.objects.bulk_create([approver_model(step_config=dst_step, approver_user_id=uid) for uid in kept])
    ctx.change(f"{where}: шаг {src_step.step} ({src_step.step_type}) добавлен, согласующих: {len(kept)}.")
    if src_step.is_enabled and not kept:
        ctx.warn(f"{where}: шаг {src_step.step} создан выключенным — нет согласующих среди участников тенанта.")
    if src_step.payment_webapp_url and not url:
        ctx.warn(f"{where}: шаг {src_step.step} — ссылка web-app оплаты пуста до настройки бота.")


def _fill_missing_bot_link(ctx, dst_step, src_step) -> None:
    if dst_step.payment_webapp_url or not src_step.payment_webapp_url:
        return
    url = ctx.bot_link(src_step.payment_webapp_url)
    if url:
        dst_step.payment_webapp_url = url
        dst_step.save(update_fields=["payment_webapp_url"])
        ctx.change(f"Шаг {dst_step.step}: ссылка web-app оплаты → {url}.")


def _clone_steps(ctx, *, src_steps, dst_steps_qs, model, approver_model, parent_field, parent, member_ids, where) -> None:
    dst_by_step = {s.step: s for s in dst_steps_qs}
    for src_step in src_steps:
        dst_step = dst_by_step.get(src_step.step)
        if dst_step is None:
            _copy_step(
                ctx, model=model, approver_model=approver_model, parent_field=parent_field, parent=parent,
                src_step=src_step, member_ids=member_ids, where=where,
            )
        else:
            _fill_missing_bot_link(ctx, dst_step, src_step)


def _clone_approvals(ctx, member_ids: set[int]) -> None:
    source_cfg = RequestApprovalConfig.objects.filter(tenant=ctx.source).first()
    if source_cfg is None:
        return
    target_cfg, created = RequestApprovalConfig.objects.get_or_create(tenant=ctx.target)
    if created and source_cfg.comment_webapp_url:
        target_cfg.comment_webapp_url = ctx.bot_link(source_cfg.comment_webapp_url)
        target_cfg.save(update_fields=["comment_webapp_url"])
    target_types = {p.payment_type: p for p in RequestApprovalPaymentTypeConfig.objects.filter(config=target_cfg)}
    target_form_cfg = RequestFormConfig.objects.filter(tenant=ctx.target).first()

    for src_pt in RequestApprovalPaymentTypeConfig.objects.filter(config=source_cfg).order_by("id"):
        where = f"Согласование «{src_pt.payment_type}»"
        dst_pt = target_types.get(src_pt.payment_type)
        if dst_pt is None:
            dst_pt = RequestApprovalPaymentTypeConfig.objects.create(
                config=target_cfg,
                payment_type=src_pt.payment_type,
                is_enabled=src_pt.is_enabled,
                request_not_required_rules=src_pt.request_not_required_rules,
            )
            ctx.change(f"{where}: тип оплаты добавлен.")
            if any(rule.get("field") == "vendor" for rule in src_pt.request_not_required_rules or []):
                ctx.warn(f"{where}: правила «заявка не нужна» ссылаются на поставщиков источника — проверьте.")

        _clone_steps(
            ctx,
            src_steps=src_pt.steps.all().order_by("step"),
            dst_steps_qs=dst_pt.steps.all(),
            model=RequestApprovalStepConfig,
            approver_model=RequestApprovalStepApproverConfig,
            parent_field="payment_type_config",
            parent=dst_pt,
            member_ids=member_ids,
            where=where,
        )

        purposes = {}
        if target_form_cfg is not None:
            purposes = {
                p.name: p
                for p in RequestPaymentPurposeConfig.objects.filter(
                    payment_type_config__config=target_form_cfg, payment_type_config__payment_type=src_pt.payment_type,
                )
            }
        linked = set(
            RequestApprovalPurposeExceptionPurpose.objects.filter(payment_type_config=dst_pt).values_list(
                "payment_purpose_id", flat=True
            )
        )
        dst_exceptions = {e.name: e for e in dst_pt.purpose_exceptions.all()}
        for src_exc in src_pt.purpose_exceptions.all().order_by("id"):
            exc_where = f"{where}, исключение «{src_exc.name or '—'}»"
            dst_exc = dst_exceptions.get(src_exc.name)
            if dst_exc is None:
                dst_exc = RequestApprovalPurposeExceptionConfig.objects.create(
                    payment_type_config=dst_pt, name=src_exc.name, is_enabled=src_exc.is_enabled,
                )
                ctx.change(f"{exc_where}: добавлено.")
            for link in src_exc.purposes.select_related("payment_purpose"):
                dst_purpose = purposes.get(link.payment_purpose.name)
                if dst_purpose is None:
                    ctx.warn(f"{exc_where}: назначения «{link.payment_purpose.name}» нет в форме — не связано.")
                    continue
                if dst_purpose.pk in linked:
                    continue
                RequestApprovalPurposeExceptionPurpose.objects.create(
                    exception_config=dst_exc, payment_type_config=dst_pt, payment_purpose=dst_purpose,
                )
                linked.add(dst_purpose.pk)
                ctx.change(f"{exc_where}: назначение «{dst_purpose.name}».")
            _clone_steps(
                ctx,
                src_steps=src_exc.steps.all().order_by("step"),
                dst_steps_qs=dst_exc.steps.all(),
                model=RequestApprovalPurposeExceptionStepConfig,
                approver_model=RequestApprovalPurposeExceptionStepApproverConfig,
                parent_field="exception_config",
                parent=dst_exc,
                member_ids=member_ids,
                where=exc_where,
            )


def clone(ctx) -> None:
    member_ids = ctx.target_member_ids()
    _clone_categories(ctx)
    _clone_form(ctx, member_ids)
    _clone_approvals(ctx, member_ids)
