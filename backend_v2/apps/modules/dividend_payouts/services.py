"""PAYED handler: a request whose payment purpose matches a tenant rule becomes an InvestReturn.

Replaces the dividend branch of the n8n «New Payed Request» workflow; the creation flow mirrors
`N8nInvestReturnPortalCreateView` (serializer validation, approvals in the transaction, routing on commit).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework import serializers

from apps.modules.dividend_payouts.models import DividendPayoutLink, DividendPayoutRule
from apps.modules.investments.approval_services import (
    create_approvals_for_invest_return,
    route_invest_return_approvals,
)
from apps.modules.investments.models import InvestReturn
from apps.modules.investments.serializers import InvestReturnSerializer
from apps.modules.investments.services import tashkent_today
from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)

SYSTEM_USER_PK = 1
ALLOWED_CURRENCIES = ("USD", "UZS")


class DividendPayoutError(Exception):
    """Expected reason why a payout could not be created (stored in DividendPayoutLink.error)."""


def normalize_purpose(value: str | None) -> str:
    return (value or "").strip()


def find_rule(tenant, purpose: str | None) -> DividendPayoutRule | None:
    """Active rule of the tenant matching the purpose (case-insensitive, outer spaces ignored)."""
    purpose = normalize_purpose(purpose)
    if not purpose or tenant is None:
        return None
    tenant_id = getattr(tenant, "pk", tenant)
    return (
        DividendPayoutRule.objects.filter(tenant_id=tenant_id, is_active=True, payment_purpose__iexact=purpose)
        .order_by("id")
        .first()
    )


def payout_date(request_obj) -> date:
    """Payment date of the request (`payed_at` is YYYYMMDD); today in Tashkent when it is empty."""
    raw = request_obj.payed_at
    if not raw:
        return tashkent_today()
    try:
        return datetime.strptime(str(raw), "%Y%m%d").date()
    except ValueError as exc:
        raise DividendPayoutError(f"Некорректная дата оплаты заявки: {raw}") from exc


def payout_comment(request_obj) -> str:
    vendor = (request_obj.vendor or "").strip() or "—"
    return f"Получатель: {vendor} (заявка #{request_obj.pk})"


def _flatten_errors(detail, prefix: str = "") -> list[str]:
    if isinstance(detail, Mapping):
        out: list[str] = []
        for key, value in detail.items():
            label = "" if key in ("detail", "non_field_errors") else f"{key}: "
            out.extend(_flatten_errors(value, prefix=label))
        return out
    if isinstance(detail, (list, tuple)):
        out = []
        for item in detail:
            out.extend(_flatten_errors(item, prefix=prefix))
        return out
    return [f"{prefix}{detail}"]


def error_text(exc: Exception) -> str:
    if isinstance(exc, serializers.ValidationError):
        return "; ".join(_flatten_errors(exc.detail)) or "Ошибка валидации"
    return str(exc) or exc.__class__.__name__


def _system_user():
    return get_user_model().objects.filter(pk=SYSTEM_USER_PK).first()


def create_invest_return_for_request(*, request_obj, rule: DividendPayoutRule) -> InvestReturn:
    """Create the payout exactly as portal-create does; raises on any validation problem."""
    currency = (request_obj.currency or "").strip().upper()
    if currency not in ALLOWED_CURRENCIES:
        raise DividendPayoutError(
            f"Валюта заявки {currency or '—'} не поддерживается для выплат инвестиций (только USD/UZS)."
        )
    system_user = _system_user()
    if system_user is None:
        raise DividendPayoutError("Системный пользователь (pk=1) не найден.")

    tenant = request_obj.tenant
    paid_on = payout_date(request_obj)
    billing = request_obj.billing_date or paid_on
    payload = {
        "date": paid_on.isoformat(),
        "billing_date": billing.isoformat(),
        "sum": str(request_obj.amount),
        "currency": currency,
        "type": rule.return_type,
        "recipient": rule.recipient,
        "comment": payout_comment(request_obj),
    }
    # The serializer reads tenant (type whitelist, companies) and method/path (client pk guard) from the request.
    fake_request = SimpleNamespace(tenant=tenant, user=system_user, method="POST", path="/internal/dividend-payouts/")
    ser = InvestReturnSerializer(data=payload, context={"request": fake_request})
    ser.is_valid(raise_exception=True)
    invest_return = ser.save(tenant=tenant, created_by=system_user)
    create_approvals_for_invest_return(invest_return=invest_return)
    return invest_return


def _route_approvals(invest_return_id: int) -> None:
    invest_return = InvestReturn.objects.filter(pk=invest_return_id).select_related("tenant").first()
    if invest_return is None:
        return
    try:
        route_invest_return_approvals(invest_return=invest_return)
    except Exception:
        logger.exception("dividend_payouts: approval routing failed invest_return_id=%s", invest_return_id)


def _handle_payed(request_obj) -> None:
    rule = find_rule(request_obj.tenant_id, request_obj.payment_purpose)
    if rule is None:
        return

    # Serialize concurrent PAYED dispatches of the same request; the OneToOne link is the final guard.
    Request.objects.select_for_update().filter(pk=request_obj.pk).values_list("pk", flat=True).first()
    if DividendPayoutLink.objects.filter(
        request_id=request_obj.pk, status=DividendPayoutLink.Status.CREATED
    ).exists():
        logger.info("dividend_payouts: repeated PAYED ignored request_id=%s", request_obj.pk)
        return
    # A FAILED link (e.g. CBU rate gap) is retried: the row is reused and overwritten below.

    try:
        with transaction.atomic():
            invest_return = create_invest_return_for_request(request_obj=request_obj, rule=rule)
    except Exception as exc:
        logger.exception(
            "dividend_payouts: invest return not created request_id=%s tenant_id=%s rule_id=%s",
            request_obj.pk, request_obj.tenant_id, rule.pk,
        )
        DividendPayoutLink.objects.update_or_create(
            request=request_obj,
            defaults={
                "rule": rule,
                "invest_return": None,
                "status": DividendPayoutLink.Status.FAILED,
                "error": error_text(exc),
            },
        )
        return

    DividendPayoutLink.objects.update_or_create(
        request=request_obj,
        defaults={
            "rule": rule,
            "invest_return": invest_return,
            "status": DividendPayoutLink.Status.CREATED,
            "error": "",
        },
    )
    logger.info(
        "dividend_payouts: invest return created request_id=%s invest_return_id=%s type=%s recipient=%s",
        request_obj.pk, invest_return.pk, invest_return.type, invest_return.recipient,
    )
    invest_return_id = invest_return.pk
    transaction.on_commit(lambda: _route_approvals(invest_return_id), robust=True)


def retry_failed_link(link: DividendPayoutLink) -> DividendPayoutLink:
    """Re-run the handler for the link's request (admin «Повторить»); returns the refreshed link."""
    if link.status == DividendPayoutLink.Status.FAILED:
        request_obj = Request.objects.select_related("tenant").get(pk=link.request_id)
        on_request_payed(request_obj=request_obj)
        link.refresh_from_db()
    return link


def on_request_payed(*, request_obj) -> None:
    """Registered PAYED handler (see apps.DividendPayoutsConfig.ready). Never breaks the payment flow.

    Own savepoint: `dispatch_request_payed_event_handlers` opens none, so a DB error here would
    otherwise abort the caller's transaction.
    """
    try:
        with transaction.atomic():
            _handle_payed(request_obj)
    except Exception:
        logger.exception(
            "dividend_payouts: payed handler failed request_id=%s tenant_id=%s",
            getattr(request_obj, "pk", None), getattr(request_obj, "tenant_id", None),
        )
