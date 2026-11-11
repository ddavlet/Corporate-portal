"""Investment module integrations (CBU rates, etc.)."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# Без даты в пути API отдаёт курсы прошлой недели, а не «на сегодня».
# Документация: .../json/all/YYYY-MM-DD/ — все валюты на дату.
CBU_JSON_BASE = "https://cbu.uz/ru/arkhiv-kursov-valyut/json"
UZ_TASHKENT = ZoneInfo("Asia/Tashkent")


class CbuRateFetchError(Exception):
    """Failed to load or parse CBU bulletin."""


def tashkent_today() -> date:
    """Текущая календарная дата в часовом поясе Ташкента."""
    return timezone.now().astimezone(UZ_TASHKENT).date()


def clamp_rate_date_to_cbu_availability(*, requested: date) -> date:
    """В архиве ЦБ нет «будущих» дат — не выходим за сегодня по Ташкенту."""
    today = tashkent_today()
    if requested > today:
        return today
    return requested


def _cbu_rows_from_payload(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def fetch_cbu_rows_for_date(*, rate_date: date, timeout: int = 12) -> list[dict]:
    """
    Сырые строки бюллетеня ЦБ РУз на дату ``rate_date`` (UZS за Nominal единиц валюты).

    Адрес — ``settings.CBU_RATES_BASE_URL`` (ретранслятор на kolberg-tash: cbu.uz не пускает неузбекские IP),
    по умолчанию cbu.uz напрямую.
    """
    d = clamp_rate_date_to_cbu_availability(requested=rate_date)
    base = getattr(settings, "CBU_RATES_BASE_URL", "") or CBU_JSON_BASE
    url = f"{base}/all/{d.isoformat()}/"
    token = getattr(settings, "CBU_RATES_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        rows = _cbu_rows_from_payload(resp.json())
    except (OSError, ValueError, requests.RequestException) as exc:
        logger.exception("CBU bulletin request failed for %s", url)
        raise CbuRateFetchError("Не удалось получить курсы с сайта ЦБ РУз.") from exc

    if not rows:
        raise CbuRateFetchError("Неожиданный ответ ЦБ РУз (ожидался список курсов).")
    return rows


def _parse_cbu_nominal_rate(row: dict) -> tuple[Decimal, Decimal]:
    nominal = Decimal(str(row.get("Nominal", "1")).replace(",", "."))
    rate = Decimal(str(row.get("Rate", "")).replace(",", "."))
    if nominal <= 0:
        raise CbuRateFetchError("Некорректный номинал валюты в ответе ЦБ РУз.")
    return nominal, rate


def usd_uzs_rate_from_cbu_rows(rows: list[dict]) -> Decimal:
    """UZS за 1 USD по строке USD в бюллетене."""
    for row in rows:
        if str(row.get("Ccy", "")).strip().upper() != "USD":
            continue
        try:
            nominal, rate = _parse_cbu_nominal_rate(row)
        except (InvalidOperation, TypeError) as exc:
            raise CbuRateFetchError("Не удалось разобрать курс USD в ответе ЦБ РУз.") from exc
        return (rate / nominal).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    raise CbuRateFetchError("В ответе ЦБ РУз не найден курс USD.")


def uzs_per_unit_for_currency_from_cbu_rows(rows: list[dict], currency: str) -> Decimal | None:
    """
    Сколько сум за 1 единицу валюты ``currency`` (с учётом Nominal в строке ЦБ).
    Для UZS возвращает 1 (сумма уже в сумах).
    """
    cur = str(currency or "").strip().upper()
    if cur == "UZS":
        return Decimal("1")
    for row in rows:
        if str(row.get("Ccy", "")).strip().upper() != cur:
            continue
        try:
            nominal, rate = _parse_cbu_nominal_rate(row)
        except (InvalidOperation, TypeError):
            return None
        return (rate / nominal).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return None


def invest_return_cbu_usd_rate_and_sum_uzs_from_bulletin(
    *,
    sum_val: Decimal,
    currency: str,
    rows: list[dict],
) -> tuple[Decimal, Decimal]:
    """
    По бюллетеню ЦБ на одну дату: (cbu_usd_uzs_rate, sum_uzs).

    ``cbu_usd_uzs_rate`` — UZS за 1 USD; ``sum_uzs`` = sum * (UZS за единицу валюты выплаты).
    """
    usd_rate = usd_uzs_rate_from_cbu_rows(rows)
    mult = uzs_per_unit_for_currency_from_cbu_rows(rows, currency)
    if mult is None:
        raise CbuRateFetchError(f"В ответе ЦБ РУз не найдена валюта {str(currency or '').strip().upper()!r}.")
    sum_uzs = (sum_val * mult).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return usd_rate.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), sum_uzs


def fetch_cbu_usd_uzs_rate(*, rate_date: date, timeout: int = 12) -> Decimal:
    """
    Официальный курс ЦБ РУз: UZS за 1 USD на дату ``rate_date``.
    """
    rows = fetch_cbu_rows_for_date(rate_date=rate_date, timeout=timeout)
    return usd_uzs_rate_from_cbu_rows(rows)


CBU_ARCHIVE_EMPTY_MESSAGE = "Курсы ЦБ ещё не загружены, попробуйте позже."


def usd_uzs_equivalents(*, sum_val: Decimal, currency: str, rate_date: date) -> tuple[Decimal, Decimal]:
    """
    (сумма в USD, сумма в UZS) по курсу из архива CbuExchangeRate — на ``rate_date``, иначе
    ближайший предыдущий (см. usd_uzs_rate_on_or_before). Без сетевых запросов: архив пополняет
    только backend_cron (sync_cbu_exchange_rate). Поднимает CbuRateFetchError, если архив пуст.
    """
    rate = usd_uzs_rate_on_or_before(rate_date)
    if rate is None:
        raise CbuRateFetchError(CBU_ARCHIVE_EMPTY_MESSAGE)
    return _equivalents_from_rate(sum_val=sum_val, currency=currency, rate=rate)


def _equivalents_from_rate(*, sum_val: Decimal, currency: str, rate: Decimal) -> tuple[Decimal, Decimal]:
    d_sum = Decimal(str(sum_val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cur = str(currency or "USD").strip().upper()
    if cur == "UZS":
        sum_uzs = d_sum
        sum_usd = (d_sum / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        sum_usd = d_sum
        sum_uzs = (d_sum * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return sum_usd, sum_uzs


def usd_uzs_equivalents_or_none(
    *, sum_val: Decimal, currency: str, rate_date: date
) -> tuple[Decimal | None, Decimal | None]:
    """То же самое, но (None, None) вместо исключения, если курс недоступен (для чтения/отчётов)."""
    try:
        return usd_uzs_equivalents(sum_val=sum_val, currency=currency, rate_date=rate_date)
    except CbuRateFetchError:
        return None, None


def usd_uzs_equivalents_for_read(
    *, sum_val: Decimal, currency: str, rate_date: date, memo: dict
) -> tuple[Decimal | None, Decimal | None]:
    """
    (сумма в USD, сумма в UZS) для чтения списков и отчётов — без сетевых запросов.

    Курс — из архива CbuExchangeRate на ``rate_date``, иначе ближайший предыдущий (как в отчёте
    для инвесторов, см. usd_uzs_rate_on_or_before). Архив пополняет только backend_cron
    (sync_cbu_exchange_rate --fill-gaps-days). Поход на cbu.uz из запросов убран: при недоступном
    ЦБ каждое открытие списка ждало таймаут, а итоги теряли строки.
    ``memo`` — общий словарь на запрос: архив читается из БД один раз. (None, None) — архив пуст.
    """
    sum_usd, sum_uzs, _ = usd_uzs_equivalents_with_rate_date_for_read(
        sum_val=sum_val, currency=currency, rate_date=rate_date, memo=memo
    )
    return sum_usd, sum_uzs


def usd_uzs_equivalents_with_rate_date_for_read(
    *, sum_val: Decimal, currency: str, rate_date: date, memo: dict
) -> tuple[Decimal | None, Decimal | None, date | None]:
    """
    То же, что usd_uzs_equivalents_for_read, плюс дата курса ЦБ, по которому посчитано.
    Дата курса != ``rate_date`` — курс на дату ещё не загружен, использован ближайший известный
    (UI помечает такие суммы как предварительные). (None, None, None) — архив пуст.
    """
    found = usd_uzs_rate_and_date_on_or_before(rate_date, cache=memo)
    if found is None:
        return None, None, None
    rate, used_date = found
    sum_usd, sum_uzs = _equivalents_from_rate(sum_val=sum_val, currency=currency, rate=rate)
    return sum_usd, sum_uzs, used_date


_ALL_RATES_CACHE_KEY = "__all_rates__"


def usd_uzs_rate_on_or_before(rate_date: date, *, cache: dict | None = None) -> Decimal | None:
    """
    UZS за 1 USD из архива CbuExchangeRate без сетевых запросов: курс на ``rate_date``,
    иначе ближайший предыдущий, а если дата раньше архива — самый ранний курс архива.
    Пустой архив — ``None``. См. usd_uzs_rate_and_date_on_or_before.
    """
    found = usd_uzs_rate_and_date_on_or_before(rate_date, cache=cache)
    return found[0] if found is not None else None


def usd_uzs_rate_and_date_on_or_before(
    rate_date: date, *, cache: dict | None = None
) -> tuple[Decimal, date] | None:
    """
    (UZS за 1 USD, дата этого курса) из архива CbuExchangeRate без сетевых запросов: курс на
    ``rate_date``, иначе ближайший предыдущий, а если дата раньше архива — самый ранний курс
    архива. Пустой архив — ``None``.

    С ``cache`` весь архив читается одним запросом и переиспользуется (для отчётов,
    где сотни строк с разными датами).
    """
    from bisect import bisect_right

    from apps.modules.investments.models import CbuExchangeRate

    if cache is None:
        row = CbuExchangeRate.objects.filter(date__lte=rate_date).order_by("-date").first()
        if row is None:
            row = CbuExchangeRate.objects.order_by("date").first()
        return (row.usd_uzs_rate, row.date) if row is not None else None

    rates = cache.get(_ALL_RATES_CACHE_KEY)
    if rates is None:
        rates = list(CbuExchangeRate.objects.order_by("date").values_list("date", "usd_uzs_rate"))
        cache[_ALL_RATES_CACHE_KEY] = rates
    if not rates:
        return None
    idx = bisect_right(rates, rate_date, key=lambda r: r[0])
    used_date, rate = rates[idx - 1] if idx > 0 else rates[0]
    return rate, used_date


def latest_archived_cbu_rate_date(*, cache: dict | None = None) -> date | None:
    """Самая поздняя дата в архиве курсов ЦБ (None — архив пуст); с ``cache`` — без лишнего запроса."""
    from apps.modules.investments.models import CbuExchangeRate

    if cache is None:
        return CbuExchangeRate.objects.order_by("-date").values_list("date", flat=True).first()
    rates = cache.get(_ALL_RATES_CACHE_KEY)
    if rates is None:
        rates = list(CbuExchangeRate.objects.order_by("date").values_list("date", "usd_uzs_rate"))
        cache[_ALL_RATES_CACHE_KEY] = rates
    return rates[-1][0] if rates else None


def _report_chat_options(tenant) -> list[dict]:
    from apps.modules.telegram_approvals.models import TenantTelegramChat

    return [
        {"id": chat.pk, "name": chat.name}
        for chat in TenantTelegramChat.objects.filter(tenant=tenant, is_active=True).order_by("name", "id")
    ]


def get_report_config_payload(tenant) -> dict:
    """Настройки еженедельного отчёта для инвесторов (или default, если ещё не сохранены)."""
    from apps.modules.investments.models import InvestReportConfig

    config = InvestReportConfig.objects.filter(tenant=tenant).first()
    if config is None:
        config = InvestReportConfig(tenant=tenant)
    rate = config.target_annual_rate
    return {
        "is_active": config.is_active,
        "telegram_chat_id": config.telegram_chat_id,
        "weekday": config.weekday,
        "send_hour": config.send_hour,
        "target_annual_rate": str(rate) if rate is not None else None,
        "start_month": config.start_month,
        "last_payouts_count": config.last_payouts_count,
        "late_payment_day": config.late_payment_day,
        "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        "options": {"chats": _report_chat_options(tenant)},
    }


def save_report_config(*, tenant, data: dict, actor):
    from apps.modules.investments.models import InvestReportConfig

    config, _ = InvestReportConfig.objects.update_or_create(
        tenant=tenant,
        defaults={
            "is_active": data["is_active"],
            "telegram_chat_id": data.get("telegram_chat_id"),
            "weekday": data["weekday"],
            "send_hour": data["send_hour"],
            "target_annual_rate": data.get("target_annual_rate"),
            "start_month": data.get("start_month"),
            "last_payouts_count": data["last_payouts_count"],
            "late_payment_day": data["late_payment_day"],
            "updated_by": actor,
        },
    )
    return config


def list_report_dispatches_payload(tenant, *, limit: int = 20) -> list[dict]:
    """Последние отправки отчёта для таблицы на странице настроек."""
    from apps.modules.investments.models import InvestReportDispatch
    from apps.modules.telegram_approvals.models import TenantTelegramChat

    chat_names = dict(TenantTelegramChat.objects.filter(tenant=tenant).values_list("chat_id", "name"))
    rows = InvestReportDispatch.objects.filter(tenant=tenant).select_related("created_by")[:limit]
    return [report_dispatch_payload(row, chat_names=chat_names) for row in rows]


def report_dispatch_payload(dispatch, *, chat_names: dict | None = None) -> dict:
    user = dispatch.created_by
    return {
        "id": dispatch.pk,
        "report_date": dispatch.report_date.isoformat(),
        "kind": dispatch.kind,
        "status": dispatch.status,
        "chat_id": dispatch.chat_id,
        "chat_name": (chat_names or {}).get(dispatch.chat_id, ""),
        "error": dispatch.error,
        "created_by_name": ((getattr(user, "full_name", "") or user.username or "").strip() if user else ""),
        "created_at": dispatch.created_at.isoformat() if dispatch.created_at else None,
    }


def _list_investment_approval_action_items(
    *,
    tenant,
    user,
    approval_model,
    parent_field: str,
    notification_step_type: str,
) -> list:
    """Pending approval rows of `user` that sit on the current step of their flow.

    Same rule as the Telegram card state (approval_services._investment_flow_flags and
    project_investment_approval_services._project_investment_flow_flags): the current
    step is Min(step) among pending rows of the parent, and any rejected row blocks the
    whole flow. Notification rows and confirmed parents need no action.
    """
    from django.db.models import Exists, F, Min, OuterRef, Subquery

    parent_ref = OuterRef(parent_field)
    current_step = (
        approval_model.objects.filter(
            tenant=tenant,
            **{parent_field: parent_ref},
            decision=approval_model.DECISION_PENDING,
        )
        .values(parent_field)
        .annotate(value=Min("step"))
        .values("value")[:1]
    )
    has_rejected = approval_model.objects.filter(
        **{parent_field: parent_ref},
        decision=approval_model.DECISION_REJECTED,
    )
    rows = (
        approval_model.objects.filter(
            tenant=tenant,
            approver_user=user,
            decision=approval_model.DECISION_PENDING,
            **{f"{parent_field}__tenant": tenant, f"{parent_field}__confirmed": False},
        )
        .exclude(step_type=notification_step_type)
        .annotate(current_step=Subquery(current_step), blocked=Exists(has_rejected))
        .filter(blocked=False, step=F("current_step"))
        .select_related(parent_field, f"{parent_field}__company")
        .order_by(f"{parent_field}_id", "step", "id")
    )
    result = []
    seen_parent_ids: set[int] = set()
    for row in rows:
        parent_id = getattr(row, f"{parent_field}_id")
        if parent_id in seen_parent_ids:
            continue
        seen_parent_ids.add(parent_id)
        result.append(row)
    return result


def list_invest_return_action_items(*, tenant, user) -> list[dict]:
    """Investment payouts (InvestReturn) whose current approval step waits on `user`."""
    from apps.modules.investments.models import InvestmentApprovalConfigStep, InvestmentReturnApproval

    rows = _list_investment_approval_action_items(
        tenant=tenant,
        user=user,
        approval_model=InvestmentReturnApproval,
        parent_field="invest_return",
        notification_step_type=InvestmentApprovalConfigStep.STEP_TYPE_NOTIFICATION,
    )
    items: list[dict] = []
    for row in rows:
        invest_return = row.invest_return
        title = f"Выплата инвестиции #{invest_return.id}"
        if invest_return.company:
            title = f"{title} · {invest_return.company.name}"
        items.append(
            {
                "kind": "invest_return",
                "id": invest_return.id,
                "approval_id": row.id,
                "step": row.step,
                "step_type": row.step_type,
                "title": title,
                "amount": invest_return.sum,
                "currency": invest_return.currency or "",
                "type_code": invest_return.type or "",
                "type_label": invest_return.get_type_display() or "",
                "created_at": invest_return.created_at,
                "link": f"/investments?tab=returns&open={invest_return.id}",
            }
        )
    return items


def list_project_investment_action_items(*, tenant, user) -> list[dict]:
    """Project investments whose current approval step waits on `user`."""
    from apps.modules.investments.models import (
        InvestmentProjectApprovalConfigStep,
        ProjectInvestmentApproval,
    )

    rows = _list_investment_approval_action_items(
        tenant=tenant,
        user=user,
        approval_model=ProjectInvestmentApproval,
        parent_field="project_investment",
        notification_step_type=InvestmentProjectApprovalConfigStep.STEP_TYPE_NOTIFICATION,
    )
    items: list[dict] = []
    for row in rows:
        investment = row.project_investment
        title = f"Вложение в проект #{investment.id}"
        if investment.company:
            title = f"{title} · {investment.company.name}"
        items.append(
            {
                "kind": "project_investment",
                "id": investment.id,
                "approval_id": row.id,
                "step": row.step,
                "step_type": row.step_type,
                "title": title,
                "amount": investment.amount,
                "currency": investment.currency or "",
                "type_code": investment.funding_method or "",
                "type_label": investment.get_funding_method_display() if investment.funding_method else "",
                "created_at": investment.created_at,
                "link": f"/investments?tab=investments&open={investment.id}",
            }
        )
    return items
