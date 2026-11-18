"""
Automatic "Платежная карта" requests for corporate card expenses.

For a CardExpense on a card with an enabled CardExpenseAutoRequestConfig and no
linked request (after amount/date reconciliation):
  (b) close an approved, not yet paid card request of the same amount/currency
      (see card_expense_pending_request_close), or
  (c) create one PAYED request backdated to the expense date, linked to the expense,
      with a comment from the "Система" user (pk=1). No approval chain, no
      Telegram, no PAYED handlers.

Idempotency: the CardExpense row is locked (select_for_update) and links are checked
through Request.all_objects, so deleted requests also count as "already linked".

Nothing is created or closed while the tenant's corporate_card module is switched off
or the configured payment purpose is no longer active (graceful degradation).

Called from n8n_integration (card-expense upsert/batch, after reconciliation, via
transaction.on_commit so the Kapitalbank import runs it only after its own commit) and
from the backfill_card_expense_auto_requests management command.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.modules.corporate_card.auto_request_config import active_card_payment_purposes
from apps.modules.corporate_card.models import CardExpense, CardExpenseAutoRequestConfig
from apps.modules.requests.card_expense_pending_request_close import (
    card_expense_currency,
    card_expense_local_date,
    close_pending_request_for_card_expense,
    find_closable_pending_request,
    format_card_expense_amount,
)
from apps.modules.requests.command_options import date_to_payed_at, system_user
from apps.modules.requests.models import (
    Request,
    RequestComment,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.requests.request_required import is_request_required_for_expense
from apps.tenants.models import TenantModuleConfig

logger = logging.getLogger(__name__)

ACTION_CLOSED = "closed"
ACTION_CREATED = "created"
ACTION_SKIPPED = "skipped"

CORPORATE_CARD_MODULE_KEY = "corporate_card"

_SUPPORTED_CURRENCIES = frozenset(code for code, _ in Request.CURRENCY_CHOICES)
_VENDOR_NAME_MAX_LENGTH = Request._meta.get_field("vendor").max_length
# "Not passed" marker for the system user (None means "user pk=1 does not exist").
_UNSET = object()


@dataclass(frozen=True)
class AutoRequestResult:
    action: str  # "closed" | "created" | "skipped"
    request_id: int | None
    reason: str = ""


def expense_matches_config(expense, config) -> bool:
    """Enabled config of the expense's card whose "description contains" condition matches."""
    if config is None or not config.is_enabled:
        return False
    if config.wallet_id != expense.wallet_id or config.tenant_id != expense.tenant_id:
        return False
    needle = str(config.match_text or "").strip().casefold()
    if not needle:
        return True
    haystack = f"{expense.note or ''}\n{expense.title or ''}".casefold()
    return needle in haystack


def _card_expense_link_q(expense) -> Q:
    keys = {str(expense.pk)}
    external_id = str(expense.external_id or "").strip()
    if external_id:
        keys.add(external_id)
    return Q(expense_ref_target=Request.EXPENSE_REF_TARGET_CARD, expense_ref_id=expense.pk) | Q(
        payment_type=Request.PAYMENT_TYPE_CARD, expense_id__in=keys
    )


def is_corporate_card_module_enabled(tenant_id) -> bool:
    return TenantModuleConfig.objects.filter(
        tenant_id=tenant_id, module_key=CORPORATE_CARD_MODULE_KEY, is_enabled=True
    ).exists()


def _is_active_card_purpose(*, tenant, payment_purpose: str) -> bool:
    return payment_purpose in {row["name"] for row in active_card_payment_purposes(tenant)}


def is_card_expense_linked(expense) -> bool:
    """Any request (deleted included) already points to this expense."""
    return Request.all_objects.filter(tenant_id=expense.tenant_id).filter(_card_expense_link_q(expense)).exists()


def find_auto_request_candidates(
    *,
    tenant,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> list[tuple[CardExpense, CardExpenseAutoRequestConfig]]:
    """Unlinked expenses on cards with an enabled, matching config; ordered by (expense_at, id)."""
    if not is_corporate_card_module_enabled(tenant.id):
        return []
    configs = {
        cfg.wallet_id: cfg
        for cfg in CardExpenseAutoRequestConfig.objects.filter(tenant=tenant, is_enabled=True).select_related(
            "vendor_ref"
        )
    }
    if not configs:
        return []
    qs = CardExpense.objects.filter(tenant=tenant, wallet_id__in=list(configs))
    if date_from:
        qs = qs.filter(expense_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_at__date__lte=date_to)

    linked_ref_ids = set(
        Request.all_objects.filter(
            tenant=tenant,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
            expense_ref_id__isnull=False,
        ).values_list("expense_ref_id", flat=True)
    )
    linked_expense_keys = set(
        Request.all_objects.filter(tenant=tenant, payment_type=Request.PAYMENT_TYPE_CARD)
        .exclude(expense_id__isnull=True)
        .exclude(expense_id="")
        .values_list("expense_id", flat=True)
    )

    result: list[tuple[CardExpense, CardExpenseAutoRequestConfig]] = []
    for expense in qs.order_by("expense_at", "id"):
        config = configs[expense.wallet_id]
        if not expense_matches_config(expense, config):
            continue
        if expense.pk in linked_ref_ids or str(expense.pk) in linked_expense_keys:
            continue
        external_id = str(expense.external_id or "").strip()
        if external_id and external_id in linked_expense_keys:
            continue
        result.append((expense, config))
    return result


def _skip_reason(expense, config, *, actor) -> str:
    if config is None:
        return "для карты нет настройки автозаявок"
    if not config.is_enabled:
        return "настройка автозаявок карты выключена"
    if config.tenant_id != expense.tenant_id or config.wallet_id != expense.wallet_id:
        return "настройка автозаявок относится к другой карте"
    if not is_corporate_card_module_enabled(expense.tenant_id):
        return "модуль «Корпоративные карты» у компании выключен"
    payment_purpose = str(config.payment_purpose or "").strip()
    if not payment_purpose:
        return "в настройке автозаявок не указано назначение платежа"
    if not _is_active_card_purpose(tenant=expense.tenant, payment_purpose=payment_purpose):
        logger.warning(
            "card_expense_auto_request: inactive payment purpose expense_id=%s config_id=%s",
            expense.pk,
            config.pk,
        )
        return f"назначение «{payment_purpose}» не активно для «Платежная карта»"
    if not expense_matches_config(expense, config):
        return f"описание расхода не содержит «{config.match_text}»"
    if is_card_expense_linked(expense):
        return "расход уже связан с заявкой"
    if not is_request_required_for_expense(
        tenant=expense.tenant,
        payment_type=Request.PAYMENT_TYPE_CARD,
        expense_obj=expense,
    ):
        return "по правилам компании заявка для расхода не нужна"
    currency = card_expense_currency(expense)
    if currency not in _SUPPORTED_CURRENCIES:
        logger.warning(
            "card_expense_auto_request: unsupported currency expense_id=%s currency=%s", expense.pk, currency
        )
        return f"валюта {currency or '—'} не поддерживается заявками"
    if actor is None:
        logger.warning("card_expense_auto_request: system user pk=1 not found expense_id=%s", expense.pk)
        return "нет пользователя «Система» (pk=1)"
    return ""


def plan_card_expense_auto_request(
    expense, config, *, reserved_request_ids: set[int], actor=_UNSET
) -> AutoRequestResult:
    """Read-only (dry-run) counterpart of process_card_expense_auto_request.

    The picked request id is added to `reserved_request_ids`, so consecutive calls
    plan the same closures as the sequential --apply run. Pass `actor` (the system
    user) to avoid looking it up for every expense.
    """
    if actor is _UNSET:
        actor = system_user()
    reason = _skip_reason(expense, config, actor=actor)
    if reason:
        return AutoRequestResult(action=ACTION_SKIPPED, request_id=None, reason=reason)
    request_obj = find_closable_pending_request(
        expense=expense,
        preferred_purpose=config.payment_purpose,
        exclude_ids=frozenset(reserved_request_ids),
    )
    if request_obj is not None:
        reserved_request_ids.add(request_obj.pk)
        return AutoRequestResult(action=ACTION_CLOSED, request_id=request_obj.pk)
    return AutoRequestResult(action=ACTION_CREATED, request_id=None)


def process_card_expense_auto_request(expense_id: int, *, actor=_UNSET) -> AutoRequestResult:
    """Pass `actor` (the system user) to avoid looking it up for every expense."""
    with transaction.atomic():
        expense = (
            CardExpense.objects.select_for_update(of=("self",))
            .select_related("tenant")
            .filter(pk=expense_id)
            .first()
        )
        if expense is None:
            return AutoRequestResult(action=ACTION_SKIPPED, request_id=None, reason="расход не найден")
        config = (
            CardExpenseAutoRequestConfig.objects.select_related("vendor_ref")
            .filter(wallet_id=expense.wallet_id)
            .first()
        )
        if actor is _UNSET:
            actor = system_user()
        reason = _skip_reason(expense, config, actor=actor)
        if reason:
            return AutoRequestResult(action=ACTION_SKIPPED, request_id=None, reason=reason)

        closed = close_pending_request_for_card_expense(
            expense=expense,
            preferred_purpose=config.payment_purpose,
            system_user=actor,
            config=config,
        )
        if closed is not None:
            return AutoRequestResult(action=ACTION_CLOSED, request_id=closed.pk)

        request_obj = _create_auto_request(expense, config, actor)
        return AutoRequestResult(action=ACTION_CREATED, request_id=request_obj.pk)


def run_card_expense_auto_requests_hook(*, tenant, expense_ids) -> int:
    """Post-import hook: process new expenses one by one. Never raises.

    Expenses of cards without an enabled config are dropped by one query before any
    row is locked. Returns the number of requests closed or created.
    """
    try:
        ids = sorted({int(x) for x in expense_ids if x is not None})
        if not ids:
            return 0
        if not is_corporate_card_module_enabled(tenant.id):
            return 0
        enabled_wallet_ids = CardExpenseAutoRequestConfig.objects.filter(tenant=tenant, is_enabled=True).values(
            "wallet_id"
        )
        ordered_ids = list(
            CardExpense.objects.filter(tenant=tenant, id__in=ids, wallet_id__in=enabled_wallet_ids)
            .order_by("expense_at", "id")
            .values_list("id", flat=True)
        )
        if not ordered_ids:
            return 0
        actor = system_user()
    except Exception:
        logger.exception(
            "card_expense_auto_requests_hook: failed to load expenses tenant_id=%s",
            getattr(tenant, "id", None),
        )
        return 0

    done = 0
    for expense_id in ordered_ids:
        try:
            result = process_card_expense_auto_request(expense_id, actor=actor)
        except Exception:
            logger.exception(
                "card_expense_auto_requests_hook: failed tenant_id=%s expense_id=%s",
                getattr(tenant, "id", None),
                expense_id,
            )
            continue
        if result.action in (ACTION_CLOSED, ACTION_CREATED):
            done += 1
    return done


def _purpose_category(*, tenant, payment_purpose: str) -> str:
    return (
        RequestPaymentPurposeConfig.objects.filter(
            payment_type_config__config__tenant=tenant,
            payment_type_config__payment_type=Request.PAYMENT_TYPE_CARD,
            name=payment_purpose,
        )
        .order_by("-is_active", "id")
        .values_list("category", flat=True)
        .first()
        or ""
    )


def _default_company_payer(*, tenant) -> str:
    return (
        RequestFormPaymentTypeConfig.objects.filter(
            config__tenant=tenant,
            payment_type=Request.PAYMENT_TYPE_CARD,
        )
        .values_list("default_company_payer", flat=True)
        .first()
        or ""
    )


def _create_auto_request(expense, config, system_user) -> Request:
    tenant = expense.tenant
    local_dt = timezone.localtime(expense.expense_at)
    expense_date = local_dt.date()
    currency = card_expense_currency(expense)
    payment_purpose = config.payment_purpose.strip()
    vendor = config.vendor_ref if config.vendor_ref and config.vendor_ref.tenant_id == expense.tenant_id else None

    request_obj = Request.objects.create(
        tenant=tenant,
        created_by=system_user,
        requester=system_user,
        created_at=local_dt,
        submitted_at=local_dt,
        status=Request.STATUS_PAYED,
        payed_at=date_to_payed_at(expense_date),
        payment_type=Request.PAYMENT_TYPE_CARD,
        amount=expense.amount,
        currency=currency,
        description=str(expense.note or "").strip() or str(expense.title or "").strip(),
        payment_purpose=payment_purpose,
        category=(config.category or "").strip() or _purpose_category(tenant=tenant, payment_purpose=payment_purpose),
        company_payer=(config.company_payer or "").strip() or _default_company_payer(tenant=tenant),
        vendor_ref=vendor,
        vendor=vendor.name[:_VENDOR_NAME_MAX_LENGTH] if vendor else "",
        billing_date=expense_date.replace(day=1),
        expense_year=expense_date.year,
        expense_month=expense_date.month,
        expense_day=expense_date.day,
        expense_id=str(expense.pk),
        expense_ref_id=expense.pk,
        expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
    )
    RequestComment.objects.create(
        request=request_obj,
        created_by=system_user,
        body=(
            f"Заявка создана автоматически по расходу корпоративной карты {expense.pk} "
            f"от {card_expense_local_date(expense):%d.%m.%Y} на "
            f"{format_card_expense_amount(expense.amount)} {currency} по настройке автозаявок карты."
        ),
    )
    return request_obj
