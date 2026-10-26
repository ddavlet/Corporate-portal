"""
Align request categories and payment purposes across several tenants to one
target list described by a JSON plan (see purpose_alignment_plans/).

Request.payment_purpose / Request.category are plain strings copied from the
form config at creation time, so renaming a purpose in the form config alone
would split reports and budgets in two. A plan therefore has four parts,
applied per tenant in this order:

  1. renames        — old purpose name(s) -> new name within a payment type:
                      the form-config row is renamed (or, if the new name
                      already exists, deactivated and its approval-exception
                      links moved over), and request history / auto-request
                      templates / default purposes are rewritten.
  2. request_moves  — individual requests whose purpose was picked wrongly get
                      a new purpose and its category.
  3. categories     — listed categories exist and are active, others are
                      deactivated.
  4. purposes       — listed purposes exist, are active and carry the listed
                      category; every other purpose of that payment type is
                      deactivated.

Nothing is ever deleted (the settings UI deactivates purposes for the same
reason: approval-exception links cascade on delete). Every rewritten request
gets a RequestComment from "Система". Dry-run runs the same code inside a
rolled-back transaction, so the report shows exactly what --apply would do.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.apps import apps as django_apps
from django.db import transaction

from apps.modules.requests.command_options import system_user
from apps.modules.requests.models import (
    AutoRequestTemplate,
    Request,
    RequestApprovalPurposeExceptionPurpose,
    RequestCategory,
    RequestComment,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant

PLANS_DIR = Path(__file__).resolve().parent / "purpose_alignment_plans"

_PAYMENT_TYPES = {value for value, _ in Request.PAYMENT_TYPE_CHOICES}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class PurposeSpec:
    payment_type: str
    name: str
    category: str


@dataclass(frozen=True)
class RenameSpec:
    payment_type: str
    old_names: tuple[str, ...]
    new_name: str


@dataclass(frozen=True)
class RequestMoveSpec:
    tenant: str
    request_id: int
    payment_type: str
    from_purpose: str
    to_purpose: str


@dataclass(frozen=True)
class AlignmentPlan:
    tenants: tuple[str, ...]
    categories: tuple[str, ...]
    purposes: tuple[PurposeSpec, ...]
    renames: tuple[RenameSpec, ...] = ()
    request_moves: tuple[RequestMoveSpec, ...] = ()

    def purposes_for(self, payment_type: str) -> list[PurposeSpec]:
        return [p for p in self.purposes if p.payment_type == payment_type]

    def category_of(self, payment_type: str, name: str) -> str | None:
        for p in self.purposes:
            if p.payment_type == payment_type and p.name == name:
                return p.category
        return None


@dataclass
class TenantAlignmentReport:
    tenant: Tenant
    changes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requests_rewritten: int = 0


def _require_payment_type(value, where: str) -> str:
    if value not in _PAYMENT_TYPES:
        raise PlanError(f"{where}: unknown payment type {value!r}.")
    return value


def _clean(value, where: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PlanError(f"{where}: empty name.")
    return text


def parse_plan(data: dict) -> AlignmentPlan:
    tenants = tuple(str(t).strip() for t in data.get("tenants") or [] if str(t).strip())
    if not tenants:
        raise PlanError("Plan has no tenants.")

    categories = tuple(_clean(c, "categories") for c in data.get("categories") or [])
    if len(set(categories)) != len(categories):
        raise PlanError("categories: duplicate names.")

    purposes: list[PurposeSpec] = []
    for payment_type, items in (data.get("purposes") or {}).items():
        _require_payment_type(payment_type, "purposes")
        seen: set[str] = set()
        for item in items:
            name, category = (_clean(v, f"purposes[{payment_type}]") for v in item)
            if name in seen:
                raise PlanError(f"purposes[{payment_type}]: duplicate {name!r}.")
            if category not in categories:
                raise PlanError(f"purposes[{payment_type}]: category {category!r} of {name!r} is not in categories.")
            seen.add(name)
            purposes.append(PurposeSpec(payment_type=payment_type, name=name, category=category))

    renames = tuple(
        RenameSpec(
            payment_type=_require_payment_type(r.get("payment_type"), "renames"),
            old_names=tuple(_clean(n, "renames.from") for n in r.get("from") or []),
            new_name=_clean(r.get("to"), "renames.to"),
        )
        for r in data.get("renames") or []
    )

    plan = AlignmentPlan(tenants=tenants, categories=categories, purposes=tuple(purposes), renames=renames)

    moves: list[RequestMoveSpec] = []
    for m in data.get("request_moves") or []:
        move = RequestMoveSpec(
            tenant=str(m.get("tenant") or "").strip(),
            request_id=int(m.get("request_id")),
            payment_type=_require_payment_type(m.get("payment_type"), "request_moves"),
            from_purpose=_clean(m.get("from"), "request_moves.from"),
            to_purpose=_clean(m.get("to"), "request_moves.to"),
        )
        if move.tenant not in tenants:
            raise PlanError(f"request_moves: request {move.request_id} tenant {move.tenant!r} is not in tenants.")
        if plan.category_of(move.payment_type, move.to_purpose) is None:
            raise PlanError(
                f"request_moves: request {move.request_id} target {move.to_purpose!r} "
                f"is not a {move.payment_type!r} purpose of the plan."
            )
        moves.append(move)

    return AlignmentPlan(
        tenants=tenants, categories=categories, purposes=tuple(purposes), renames=renames, request_moves=tuple(moves),
    )


def load_plan(path: str | Path) -> AlignmentPlan:
    candidate = Path(path)
    if not candidate.exists() and not candidate.suffix:
        candidate = PLANS_DIR / f"{path}.json"
    if not candidate.exists():
        raise PlanError(f"Plan {path!r} not found.")
    return parse_plan(json.loads(candidate.read_text(encoding="utf-8")))


def _comment(*, request_ids: list[int], body: str, author) -> None:
    if author is None:
        return
    RequestComment.objects.bulk_create(
        [RequestComment(request_id=rid, created_by=author, body=body) for rid in request_ids]
    )


def _payment_type_config(*, form_config, payment_type: str, report: TenantAlignmentReport):
    pt_cfg = RequestFormPaymentTypeConfig.objects.filter(config=form_config, payment_type=payment_type).first()
    if pt_cfg is None:
        # Created disabled: aligning the dictionary must not switch a payment type on for a tenant.
        pt_cfg = RequestFormPaymentTypeConfig.objects.create(
            config=form_config, payment_type=payment_type, is_enabled=False,
        )
        report.warnings.append(f"{payment_type}: тип оплаты не был настроен — создан выключенным.")
    return pt_cfg


def _warn_on_foreign_string_refs(*, tenant, payment_type: str, old: str, report: TenantAlignmentReport) -> None:
    """Budgets and cash-withdrawal rules live in optional modules; report, don't rewrite."""
    try:
        budget_model = django_apps.get_model("budgets", "Budget")
        rule_model = django_apps.get_model("cash_withdrawals", "CashWithdrawalRule")
    except LookupError:
        return
    if budget_model.objects.filter(tenant=tenant, payment_purpose=old).exists():
        report.warnings.append(f"Бюджет ссылается на «{old}» — поправьте вручную.")
    if rule_model.objects.filter(config__tenant=tenant, payment_type=payment_type, payment_purpose=old).exists():
        report.warnings.append(f"Правило инкассации ({payment_type}) ссылается на «{old}» — поправьте вручную.")


def _apply_rename(*, tenant, pt_cfg, spec: RenameSpec, author, report: TenantAlignmentReport) -> None:
    rows = {row.name: row for row in RequestPaymentPurposeConfig.objects.filter(payment_type_config=pt_cfg)}
    for old in spec.old_names:
        old_row = rows.get(old)
        new_row = rows.get(spec.new_name)
        if old_row is not None and new_row is None:
            old_row.name = spec.new_name
            old_row.save(update_fields=["name"])
            rows[spec.new_name] = rows.pop(old)
            report.changes.append(f"{spec.payment_type}: назначение «{old}» переименовано в «{spec.new_name}».")
        elif old_row is not None:
            if old_row.is_active:
                old_row.is_active = False
                old_row.save(update_fields=["is_active"])
            linked_new = RequestApprovalPurposeExceptionPurpose.objects.filter(
                payment_type_config__config__tenant=tenant, payment_purpose=new_row,
            ).exists()
            links = RequestApprovalPurposeExceptionPurpose.objects.filter(payment_purpose=old_row)
            if links.exists() and not linked_new:
                links.update(payment_purpose=new_row)
                report.changes.append(
                    f"{spec.payment_type}: исключения согласования перенесены с «{old}» на «{spec.new_name}»."
                )
            report.changes.append(
                f"{spec.payment_type}: назначение «{old}» отключено, используется «{spec.new_name}»."
            )

        if pt_cfg.default_payment_purpose == old:
            pt_cfg.default_payment_purpose = spec.new_name
            pt_cfg.save(update_fields=["default_payment_purpose"])
            report.changes.append(f"{spec.payment_type}: назначение по умолчанию → «{spec.new_name}».")

        templates = AutoRequestTemplate.objects.filter(
            tenant=tenant, payment_type=spec.payment_type, payment_purpose=old,
        )
        n_templates = templates.update(payment_purpose=spec.new_name)
        if n_templates:
            report.changes.append(f"{spec.payment_type}: автозаявок с «{old}» → «{spec.new_name}»: {n_templates}.")

        # all_objects: deleted/draft requests are history too and must not keep the old spelling.
        request_ids = list(
            Request.all_objects.filter(
                tenant=tenant, payment_type=spec.payment_type, payment_purpose=old,
            ).order_by("id").values_list("id", flat=True)
        )
        if request_ids:
            Request.all_objects.filter(id__in=request_ids).update(payment_purpose=spec.new_name)
            _comment(
                request_ids=request_ids,
                author=author,
                body=(
                    f"Назначение платежа изменено автоматически при выравнивании справочника назначений: "
                    f"«{old}» → «{spec.new_name}»."
                ),
            )
            report.requests_rewritten += len(request_ids)
            report.changes.append(
                f"{spec.payment_type}: заявок «{old}» → «{spec.new_name}»: {len(request_ids)} "
                f"(#{', #'.join(map(str, request_ids[:10]))}{' …' if len(request_ids) > 10 else ''})."
            )
        _warn_on_foreign_string_refs(tenant=tenant, payment_type=spec.payment_type, old=old, report=report)


def _apply_request_move(*, tenant, plan: AlignmentPlan, move: RequestMoveSpec, author, report) -> None:
    request = Request.all_objects.filter(pk=move.request_id, tenant=tenant).first()
    if request is None:
        report.warnings.append(f"Заявка #{move.request_id} не найдена в тенанте — пропущена.")
        return
    if request.payment_type != move.payment_type or request.payment_purpose != move.from_purpose:
        if request.payment_type == move.payment_type and request.payment_purpose == move.to_purpose:
            return  # already moved by a previous run
        report.warnings.append(
            f"Заявка #{request.pk}: ожидалось {move.payment_type} / «{move.from_purpose}», "
            f"а сейчас {request.payment_type} / «{request.payment_purpose}» — пропущена."
        )
        return
    new_category = plan.category_of(move.payment_type, move.to_purpose)
    Request.all_objects.filter(pk=request.pk).update(payment_purpose=move.to_purpose, category=new_category)
    _comment(
        request_ids=[request.pk],
        author=author,
        body=(
            f"Назначение платежа исправлено при выравнивании справочника назначений: "
            f"«{move.from_purpose}» → «{move.to_purpose}», категория «{request.category}» → «{new_category}»."
        ),
    )
    report.requests_rewritten += 1
    report.changes.append(
        f"Заявка #{request.pk}: «{move.from_purpose}» → «{move.to_purpose}» (категория «{new_category}»)."
    )


def _sync_categories(*, tenant, plan: AlignmentPlan, report: TenantAlignmentReport) -> None:
    existing = {c.name: c for c in RequestCategory.objects.filter(tenant=tenant)}
    for name in plan.categories:
        row = existing.get(name)
        if row is None:
            RequestCategory.objects.create(tenant=tenant, name=name, is_active=True)
            report.changes.append(f"Категория «{name}» добавлена.")
        elif not row.is_active:
            row.is_active = True
            row.save(update_fields=["is_active", "updated_at"])
            report.changes.append(f"Категория «{name}» включена.")
    for name, row in existing.items():
        if name not in plan.categories and row.is_active:
            row.is_active = False
            row.save(update_fields=["is_active", "updated_at"])
            report.changes.append(f"Категория «{name}» отключена.")


def _sync_purposes(*, pt_cfg, plan: AlignmentPlan, payment_type: str, report: TenantAlignmentReport) -> None:
    wanted = {p.name: p for p in plan.purposes_for(payment_type)}
    existing = {row.name: row for row in RequestPaymentPurposeConfig.objects.filter(payment_type_config=pt_cfg)}
    for name, spec in wanted.items():
        row = existing.get(name)
        if row is None:
            RequestPaymentPurposeConfig.objects.create(
                payment_type_config=pt_cfg, name=name, category=spec.category, is_active=True,
            )
            report.changes.append(f"{payment_type}: добавлено «{name}» ({spec.category}).")
            continue
        fields: list[str] = []
        if not row.is_active:
            row.is_active = True
            fields.append("is_active")
            report.changes.append(f"{payment_type}: включено «{name}».")
        if row.category != spec.category:
            report.changes.append(f"{payment_type}: «{name}» категория «{row.category}» → «{spec.category}».")
            row.category = spec.category
            fields.append("category")
        if fields:
            row.save(update_fields=fields)
    for name, row in existing.items():
        if name not in wanted and row.is_active:
            row.is_active = False
            row.save(update_fields=["is_active"])
            report.changes.append(f"{payment_type}: отключено «{name}».")
    if pt_cfg.default_payment_purpose and pt_cfg.default_payment_purpose not in wanted:
        report.warnings.append(
            f"{payment_type}: назначение по умолчанию «{pt_cfg.default_payment_purpose}» отключено — выберите другое."
        )


def align_tenant(*, tenant: Tenant, tenant_ref: str, plan: AlignmentPlan, apply_changes: bool) -> TenantAlignmentReport:
    report = TenantAlignmentReport(tenant=tenant)
    author = system_user()
    if author is None:
        report.warnings.append("Пользователь pk=1 («Система») не найден — комментарии к заявкам не создаются.")

    with transaction.atomic():
        form_config, created = RequestFormConfig.objects.get_or_create(tenant=tenant)
        if created:
            report.warnings.append("Конфигурация формы заявки не была настроена — создана.")

        renames_by_type: dict[str, list[RenameSpec]] = defaultdict(list)
        for spec in plan.renames:
            renames_by_type[spec.payment_type].append(spec)
        payment_types = list(dict.fromkeys([p.payment_type for p in plan.purposes] + list(renames_by_type)))
        pt_cfgs = {
            pt: _payment_type_config(form_config=form_config, payment_type=pt, report=report) for pt in payment_types
        }

        for pt, specs in renames_by_type.items():
            for spec in specs:
                _apply_rename(tenant=tenant, pt_cfg=pt_cfgs[pt], spec=spec, author=author, report=report)

        for move in plan.request_moves:
            if move.tenant == tenant_ref:
                _apply_request_move(tenant=tenant, plan=plan, move=move, author=author, report=report)

        _sync_categories(tenant=tenant, plan=plan, report=report)
        for pt in dict.fromkeys(p.payment_type for p in plan.purposes):
            _sync_purposes(pt_cfg=pt_cfgs[pt], plan=plan, payment_type=pt, report=report)

        if not apply_changes:
            transaction.set_rollback(True)
    return report
