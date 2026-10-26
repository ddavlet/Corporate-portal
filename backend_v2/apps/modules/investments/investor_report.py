"""Weekly investor report: metrics (formulas mirror the n8n draft «invReportAllTnt1»).

Only reads the ORM. The text lives in investor_report_formatter, sending in investor_report_jobs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from apps.modules.investments.services import (
    clamp_rate_date_to_cbu_availability,
    latest_archived_cbu_rate_date,
    usd_uzs_rate_and_date_on_or_before,
)

logger = logging.getLogger(__name__)

ZERO = Decimal("0")

DEFAULT_LAST_PAYOUTS_COUNT = 3
DEFAULT_LATE_PAYMENT_DAY = 25


class InvestorReportError(Exception):
    """The report cannot be built (e.g. no CBU rate to convert UZS)."""


@dataclass(frozen=True)
class ReportSettings:
    """Calculation settings: InvestReportConfig fields or preview query overrides."""

    target_annual_rate: Decimal | None = None
    start_month: int | None = None
    last_payouts_count: int = DEFAULT_LAST_PAYOUTS_COUNT
    late_payment_day: int = DEFAULT_LATE_PAYMENT_DAY

    @classmethod
    def from_config(cls, config) -> "ReportSettings":
        if config is None:
            return cls()
        return cls(
            target_annual_rate=config.target_annual_rate,
            start_month=config.start_month,
            last_payouts_count=config.last_payouts_count,
            late_payment_day=config.late_payment_day,
        )


@dataclass(frozen=True)
class ReportRow:
    """One ProjectInvestment / InvestReturn with the amount already in USD."""

    date: date
    usd: Decimal
    confirmed: bool
    billing_date: date | None = None
    type: str = ""


@dataclass(frozen=True)
class Payout:
    date: date
    billing_date: date
    usd: Decimal
    type: str


@dataclass(frozen=True)
class InvestorReport:
    today: date
    year: int
    invested: Decimal
    invested_pending: Decimal
    paid_total: Decimal
    paid_pending: Decimal
    paid_year: Decimal
    start_month: int
    last_month: int
    months: int
    paid_period: Decimal
    # Yield, % per year; None when invested == 0 or months <= 0.
    annual_rate: Decimal | None = None
    # Yield without the unpaid previous month (late_payment_day rule); month number it skips.
    annual_rate_without_last: Decimal | None = None
    skipped_month: int | None = None
    target_annual_rate: Decimal | None = None
    planned: Decimal | None = None
    last_payouts: tuple[Payout, ...] = field(default_factory=tuple)
    # (date whose CBU rate is not loaded yet, date of the rate used instead) — for the latest
    # such UZS row; None when every UZS row was converted at its own date's rate.
    preliminary_rate: tuple[date, date] | None = None

    @property
    def has_yield(self) -> bool:
        return self.annual_rate is not None

    @property
    def gap(self) -> Decimal | None:
        """План − выплачено за период (> 0 — дефицит)."""
        if self.planned is None:
            return None
        return self.planned - self.paid_period


def _sum(rows) -> Decimal:
    return sum((r.usd for r in rows), ZERO)


def compute_investor_report(
    *, today: date, investments: list[ReportRow], returns: list[ReportRow], settings: ReportSettings
) -> InvestorReport:
    """
    ``investments`` ordered by (date, id); ``returns`` — investor payouts only, ordered by
    (billing_date, date, id), as in the n8n query.
    """
    year, month = today.year, today.month
    last_month = month - 1  # last finished month of the year (0 — still January)

    inv_ok = [r for r in investments if r.confirmed]
    paid = [r for r in returns if r.confirmed]

    invested = _sum(inv_ok)
    invested_pending = _sum(r for r in investments if not r.confirmed)
    paid_total = _sum(paid)
    paid_year = _sum(r for r in paid if r.billing_date.year == year)
    paid_pending = _sum(r for r in returns if not r.confirmed)

    first_inv_this_year = next((r for r in inv_ok if r.date.year == year), None)
    start_month = settings.start_month or (first_inv_this_year.date.month + 1 if first_inv_this_year else 1)
    months = last_month - start_month + 1

    def paid_for(start: int, end: int) -> Decimal:
        return _sum(r for r in paid if r.billing_date.year == year and start <= r.billing_date.month <= end)

    paid_period = paid_for(start_month, last_month)

    annual_rate = None
    annual_rate_without_last = None
    skipped_month = None
    target = settings.target_annual_rate or None  # 0 means "no target", as in the draft
    planned = None
    if invested > 0 and months > 0:
        annual_rate = paid_period / months * 12 / invested * 100
        # The previous month may still be paid late: until late_payment_day show the yield without it.
        if (
            today.day <= settings.late_payment_day
            and months > 1
            and paid_for(last_month, last_month) == 0
            and paid_period > 0
        ):
            annual_rate_without_last = paid_for(start_month, last_month - 1) / (months - 1) * 12 / invested * 100
            skipped_month = last_month
        if target:
            planned = invested * target / 100 / 12 * months

    # Latest first; ties by billing_date desc, then the newest row (id desc) first.
    ordered = sorted(paid, key=lambda r: (r.date, r.billing_date), reverse=True)
    last_payouts = tuple(
        Payout(date=r.date, billing_date=r.billing_date, usd=r.usd, type=r.type)
        for r in ordered[: settings.last_payouts_count]
    )

    return InvestorReport(
        today=today,
        year=year,
        invested=invested,
        invested_pending=invested_pending,
        paid_total=paid_total,
        paid_pending=paid_pending,
        paid_year=paid_year,
        start_month=start_month,
        last_month=last_month,
        months=months,
        paid_period=paid_period,
        annual_rate=annual_rate,
        annual_rate_without_last=annual_rate_without_last,
        skipped_month=skipped_month,
        target_annual_rate=target if annual_rate is not None else None,
        planned=planned,
        last_payouts=last_payouts,
    )


class _PreliminaryRate:
    """The latest UZS row whose date is past the newest archived CBU rate (not loaded yet)."""

    def __init__(self, rate_cache: dict):
        self._rate_cache = rate_cache
        self.value: tuple[date, date] | None = None

    def note(self, *, rate_date: date, used_date: date) -> None:
        # Only dates after the newest archived rate are «not loaded yet»: those get filled by
        # backend_cron within the hour. Older holes in the archive (rows before it started,
        # dates never backfilled) keep the old behaviour — the reference texts depend on it.
        latest = latest_archived_cbu_rate_date(cache=self._rate_cache)
        if latest is None or rate_date <= latest or used_date == rate_date:
            return
        if self.value is None or rate_date > self.value[0]:
            self.value = (rate_date, used_date)


def _to_usd(
    *, amount: Decimal, currency: str, on_date: date, rate_cache: dict, what: str,
    preliminary: _PreliminaryRate | None = None,
) -> Decimal:
    cur = str(currency or "").strip().upper()
    if cur == "UZS":
        found = usd_uzs_rate_and_date_on_or_before(on_date, cache=rate_cache)
        if found is None:
            raise InvestorReportError("Нет курса ЦБ в архиве: суммы в UZS не перевести в USD.")
        rate, used_date = found
        if preliminary is not None:
            preliminary.note(rate_date=clamp_rate_date_to_cbu_availability(requested=on_date), used_date=used_date)
        return Decimal(amount) / rate
    if cur != "USD":
        logger.warning("investor_report: %s in %r counted as USD", what, currency)
    return Decimal(amount)


def build_investor_report(*, tenant, today: date, config) -> InvestorReport:
    """``config`` — InvestReportConfig, ReportSettings or None (defaults)."""
    from apps.modules.investments.models import InvestReturn, ProjectInvestment

    settings = config if isinstance(config, ReportSettings) else ReportSettings.from_config(config)
    rate_cache: dict = {}
    preliminary = _PreliminaryRate(rate_cache)

    investments = [
        ReportRow(
            date=row["date"],
            usd=_to_usd(
                amount=row["amount"], currency=row["currency"], on_date=row["date"], rate_cache=rate_cache,
                what=f"project_investment {row['id']}", preliminary=preliminary,
            ),
            confirmed=row["confirmed"],
        )
        for row in ProjectInvestment.objects.filter(tenant=tenant)
        .order_by("date", "id")
        .values("id", "date", "amount", "currency", "confirmed")
    ]
    # id desc inside equal (billing_date, date) so that the stable sort for «last payouts»
    # puts the newest row first; the sums do not depend on the order.
    returns = [
        ReportRow(
            date=row["date"],
            billing_date=row["billing_date"],
            usd=_to_usd(
                amount=row["sum"], currency=row["currency"], on_date=row["date"], rate_cache=rate_cache,
                what=f"invest_return {row['id']}", preliminary=preliminary,
            ),
            confirmed=row["confirmed"],
            type=row["type"] or "",
        )
        for row in InvestReturn.objects.filter(tenant=tenant, recipient=InvestReturn.Recipient.INVESTOR)
        .order_by("billing_date", "date", "-id")
        .values("id", "date", "billing_date", "sum", "currency", "confirmed", "type")
    ]
    report = compute_investor_report(today=today, investments=investments, returns=returns, settings=settings)
    if preliminary.value is not None:
        report = replace(report, preliminary_rate=preliminary.value)
    return report


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.0001")))


def report_metrics(report: InvestorReport) -> dict:
    """JSON-friendly metrics for the preview API."""
    return {
        "today": report.today.isoformat(),
        "invested": _dec(report.invested),
        "invested_pending": _dec(report.invested_pending),
        "paid_total": _dec(report.paid_total),
        "paid_pending": _dec(report.paid_pending),
        "paid_year": _dec(report.paid_year),
        "start_month": report.start_month,
        "last_month": report.last_month,
        "months": report.months,
        "paid_period": _dec(report.paid_period),
        "annual_rate": _dec(report.annual_rate),
        "annual_rate_without_last": _dec(report.annual_rate_without_last),
        "skipped_month": report.skipped_month,
        "target_annual_rate": _dec(report.target_annual_rate),
        "planned": _dec(report.planned),
        "preliminary_rate": (
            {"date": report.preliminary_rate[0].isoformat(), "rate_date": report.preliminary_rate[1].isoformat()}
            if report.preliminary_rate is not None
            else None
        ),
        "gap": _dec(report.gap),
        "last_payouts": [
            {
                "date": p.date.isoformat(),
                "billing_date": p.billing_date.isoformat(),
                "usd": _dec(p.usd),
                "type": p.type,
            }
            for p in report.last_payouts
        ],
    }
