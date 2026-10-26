"""Инвестиционный режим: пул заявок на расход для сбора вложения и сам сбор.

Заявка «собрана», если у неё есть связь с действующим вложением (без отказа в согласовании).
Отклонённое вложение освобождает заявки, связи остаются для истории; удалённое — уходит каскадом.
"""
from __future__ import annotations

from collections import OrderedDict
from decimal import Decimal
from typing import Sequence

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.modules.cashier.models import CashRevenue
from apps.modules.investments.funding import get_enabled_funding_config
from apps.modules.investments.models import (
    ProjectInvestment,
    ProjectInvestmentApproval,
    ProjectInvestmentRequestLink,
)
from apps.modules.investments.project_investment_approval_services import (
    create_approvals_for_project_investment,
    route_project_investment_approvals,
)
from apps.modules.requests.models import Request, RequestComment

REQUEST_KIND_EXPENSE = "expense"
REQUEST_KIND_TRANSFER = "transfer"

CASH_REGISTER_TRANSFER_PURPOSE = "Перевод между кассами"
_DESCRIPTION_LIMIT = 80
_POOL_STATUSES = (Request.STATUS_APPROVED, Request.STATUS_PAYED)
_CASH_POOL_PAYMENT_TYPES = (Request.PAYMENT_TYPE_INVEST_CASH, Request.PAYMENT_TYPE_CASH)
_SYSTEM_USER_PK = 1


def request_kind(request_obj: Request) -> str:
    if (
        request_obj.payment_type == Request.PAYMENT_TYPE_CASH
        and request_obj.payment_purpose == CASH_REGISTER_TRANSFER_PURPOSE
    ):
        return REQUEST_KIND_TRANSFER
    return REQUEST_KIND_EXPENSE


def _active_links(qs: QuerySet) -> QuerySet:
    rejected = ProjectInvestmentApproval.objects.filter(
        project_investment_id=OuterRef("project_investment_id"),
        decision=ProjectInvestmentApproval.DECISION_REJECTED,
    )
    return qs.filter(~Exists(rejected))


def active_link_request_ids(tenant) -> QuerySet:
    return _active_links(ProjectInvestmentRequestLink.objects.filter(tenant=tenant)).values_list(
        "request_id", flat=True
    )


def is_request_collected(request_obj: Request) -> int | None:
    """Id действующего вложения, в которое собрана заявка, или None."""
    if request_obj.pk is None:
        return None
    return (
        _active_links(ProjectInvestmentRequestLink.objects.filter(request_id=request_obj.pk))
        .order_by("-project_investment_id")
        .values_list("project_investment_id", flat=True)
        .first()
    )


def eligible_requests(*, tenant, funding_method: str) -> QuerySet:
    cfg = get_enabled_funding_config(tenant)
    if cfg is None or cfg.enabled_at is None:
        return Request.objects.none()
    qs = Request.objects.filter(
        tenant=tenant,
        status__in=_POOL_STATUSES,
        submitted_at__gte=cfg.enabled_at,
    ).exclude(id__in=active_link_request_ids(tenant))
    if funding_method == ProjectInvestment.FundingMethod.CASH:
        if cfg.cash_wallet_id is None:
            return Request.objects.none()
        qs = qs.filter(wallet_ref_id=cfg.cash_wallet_id, payment_type__in=_CASH_POOL_PAYMENT_TYPES)
    elif funding_method == ProjectInvestment.FundingMethod.BANK_TRANSFER:
        qs = qs.filter(payment_type=Request.PAYMENT_TYPE_INVEST_TRANSFER)
    else:
        return Request.objects.none()
    return qs.order_by("submitted_at", "id")


def _request_note(request_obj: Request) -> str:
    if request_kind(request_obj) == REQUEST_KIND_TRANSFER:
        return "перевод между кассами"
    text = (request_obj.description or "").strip() or (request_obj.payment_purpose or "").strip()
    return " ".join(text.split())[:_DESCRIPTION_LIMIT]


def build_default_comment(requests: Sequence[Request]) -> str:
    if not requests:
        return ""
    numbers = ", ".join(f"№{r.id}" for r in requests)
    head = f"На основании заявки {numbers}." if len(requests) == 1 else f"На основании заявок {numbers}."
    notes = []
    for r in requests:
        note = _request_note(r)
        if note:
            notes.append(f"№{r.id} — {note}")
    if not notes:
        return head
    return f"{head} {'; '.join(notes)}"


def _system_user(fallback):
    return get_user_model().objects.filter(pk=_SYSTEM_USER_PK).first() or fallback


def collect_requests_into_investments(
    *,
    tenant,
    user,
    funding_method: str,
    request_ids: list[int],
    comment: str,
    company,
) -> list[ProjectInvestment]:
    """Создаёт по вложению на каждую валюту выбранных заявок и запускает их согласование."""
    unique_ids = list(dict.fromkeys(int(i) for i in request_ids))
    if not unique_ids:
        raise ValidationError({"request_ids": "Выберите заявки."})

    with transaction.atomic():
        locked = list(
            Request.objects.select_for_update()
            .filter(tenant=tenant, id__in=unique_ids)
            .order_by("submitted_at", "id")
        )
        eligible_ids = set(
            eligible_requests(tenant=tenant, funding_method=funding_method)
            .filter(id__in=unique_ids)
            .values_list("id", flat=True)
        )
        unavailable = [i for i in unique_ids if i not in eligible_ids]
        if unavailable:
            numbers = ", ".join(f"№{i}" for i in unavailable)
            raise ValidationError({"request_ids": f"Заявки {numbers} недоступны для сбора."})

        groups: "OrderedDict[str, list[Request]]" = OrderedDict()
        for request_obj in locked:
            groups.setdefault(request_obj.currency, []).append(request_obj)

        comment_text = (comment or "").strip()
        author = _system_user(user)
        investments: list[ProjectInvestment] = []
        for currency, group in groups.items():
            investment = ProjectInvestment.objects.create(
                tenant=tenant,
                date=timezone.localdate(),
                amount=sum((r.amount for r in group), Decimal("0")),
                currency=currency,
                funding_method=funding_method,
                comment=comment_text or build_default_comment(group),
                company=company,
                confirmed=False,
                created_by=user,
            )
            ProjectInvestmentRequestLink.objects.bulk_create(
                [
                    ProjectInvestmentRequestLink(tenant=tenant, project_investment=investment, request=r)
                    for r in group
                ]
            )
            RequestComment.objects.bulk_create(
                [
                    RequestComment(
                        request=r,
                        created_by=author,
                        body=f"Заявка включена в заявку на вложение №{investment.id}.",
                    )
                    for r in group
                ]
            )
            create_approvals_for_project_investment(project_investment=investment)
            investments.append(investment)

    # Рассылка карточек согласования — после фиксации, чтобы не слать сообщения по откатившимся данным.
    for investment in investments:
        route_project_investment_approvals(project_investment=investment)
    return investments


def investment_has_cash_revenue(investment: ProjectInvestment) -> bool:
    return CashRevenue.objects.filter(
        tenant_id=investment.tenant_id, payload__project_investment_id=investment.pk
    ).exists()


# ---- защита собранной заявки (mutation guard для requests) ------------------------------------

_LOCKED_REQUEST_FIELDS = ("amount", "currency", "payment_type")
_LOCKING_STATUSES = (Request.STATUS_DELETED, Request.STATUS_REJECTED)


def _related_pk(value):
    return getattr(value, "pk", value)


def _changes_locked_fields(request_obj: Request, attrs: dict) -> bool:
    for field in _LOCKED_REQUEST_FIELDS:
        if field in attrs and attrs[field] != getattr(request_obj, field):
            return True
    if "wallet_ref" in attrs and _related_pk(attrs["wallet_ref"]) != request_obj.wallet_ref_id:
        return True
    return attrs.get("status") in _LOCKING_STATUSES


def collected_request_mutation_guard(request_obj: Request, attrs: dict) -> str | None:
    if not _changes_locked_fields(request_obj, attrs):
        return None
    investment_id = is_request_collected(request_obj)
    if investment_id is not None:
        return (
            f"Заявка входит в заявку на вложение №{investment_id}. "
            "Сначала отклоните или удалите вложение."
        )
    if attrs.get("status") == Request.STATUS_DELETED:
        # Связи с отклонёнными вложениями хранятся для истории (FK PROTECT) — удалить заявку нельзя.
        history_id = (
            ProjectInvestmentRequestLink.objects.filter(request_id=request_obj.pk)
            .order_by("-project_investment_id")
            .values_list("project_investment_id", flat=True)
            .first()
        )
        if history_id is not None:
            return (
                f"Заявка была основанием заявки на вложение №{history_id}. "
                "Сначала удалите вложение."
            )
    return None
