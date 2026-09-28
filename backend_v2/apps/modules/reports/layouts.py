"""Statement layouts: which rows a template shows and how ledger entries group into lines."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass

from apps.modules.reports.classification import (
    SECTION_INVEST_RETURNS,
    SECTION_OPERATIONAL,
    SECTION_OTHER,
    SECTION_REVENUE,
)
from apps.modules.reports.ledger import SOURCE_BANK, SOURCE_CASH, LedgerEntry

POLARITY_INCOME = "income"
POLARITY_EXPENSE = "expense"
POLARITY_NEUTRAL = "neutral"
POLARITY_RESULT = "result"


def label_hash(label: str) -> str:
    """Stable, URL-safe id part for a free-text label (category names are Cyrillic)."""
    return hashlib.sha1(label.encode("utf-8")).hexdigest()[:8]


class LineGrouping(ABC):
    """Maps a ledger entry to its path of (id part, label) pairs below a section row."""

    #: Id parts that sort first among siblings, in this order; the rest sort by amount.
    fixed_order: tuple[str, ...] = ()

    @abstractmethod
    def path(self, entry: LedgerEntry) -> tuple[tuple[str, str], ...]:
        raise NotImplementedError


class ByCategoryGrouping(LineGrouping):
    def path(self, entry: LedgerEntry) -> tuple[tuple[str, str], ...]:
        return ((label_hash(entry.category), entry.category),)


class RevenueBySourceGrouping(LineGrouping):
    """Bank receipts on one line; cash receipts under «Касса», one line per operation."""

    fixed_order = ("bank", "cash")

    def path(self, entry: LedgerEntry) -> tuple[tuple[str, str], ...]:
        if entry.source == SOURCE_BANK:
            return (("bank", "Банк"),)
        if entry.source == SOURCE_CASH:
            return (("cash", "Касса"), (label_hash(entry.category), entry.category))
        return ((label_hash(entry.category), entry.category),)


@dataclass(frozen=True)
class SectionSpec:
    id: str
    label: str
    ledger_section: str
    polarity: str
    grouping: LineGrouping | None = None
    separator_before: bool = False


@dataclass(frozen=True)
class ResultSpec:
    id: str
    label: str
    terms: tuple[tuple[str, int], ...]
    strong: bool = False
    hint: str = ""
    separator_before: bool = False


@dataclass(frozen=True)
class RatioSpec:
    id: str
    label: str
    numerator: str
    denominator: str


@dataclass(frozen=True)
class BalanceSpec:
    id: str
    label: str
    mode: str  # "open" | "close"
    flow_row: str
    strong: bool = False


@dataclass(frozen=True)
class KpiSpec:
    id: str
    label: str
    rows: tuple[str, ...]
    polarity: str
    ratio_row: str | None = None


@dataclass(frozen=True)
class ChartSpec:
    inflow_rows: tuple[str, ...]
    outflow_rows: tuple[str, ...]
    net_row: str


LayoutItem = SectionSpec | ResultSpec | RatioSpec | BalanceSpec


class StatementLayout(ABC):
    """A template's statement structure for one report. One SectionSpec per ledger section."""

    report: str
    items: tuple[LayoutItem, ...]
    kpis: tuple[KpiSpec, ...]
    chart: ChartSpec

    def sections(self) -> tuple[SectionSpec, ...]:
        return tuple(item for item in self.items if isinstance(item, SectionSpec))

    def item_ids(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.items)


class ProfessionalPnlLayout(StatementLayout):
    report = "pnl"
    items = (
        SectionSpec("rev", "Выручка", SECTION_REVENUE, POLARITY_INCOME, RevenueBySourceGrouping()),
        SectionSpec("opex", "Операционные расходы", SECTION_OPERATIONAL, POLARITY_EXPENSE, ByCategoryGrouping()),
        ResultSpec("ebit", "EBIT", (("rev", 1), ("opex", -1)), hint="операционная прибыль"),
        RatioSpec("ebit_margin", "маржа EBIT", "ebit", "rev"),
        SectionSpec("other", "Прочие расходы", SECTION_OTHER, POLARITY_EXPENSE, ByCategoryGrouping()),
        ResultSpec("net", "Чистая прибыль", (("ebit", 1), ("other", -1)), strong=True),
        RatioSpec("net_margin", "маржа чистой прибыли", "net", "rev"),
        SectionSpec(
            "inv", "Выплаты инвесторам", SECTION_INVEST_RETURNS, POLARITY_NEUTRAL, None, separator_before=True
        ),
        ResultSpec("retained", "Нераспределённая прибыль за период", (("net", 1), ("inv", -1))),
        BalanceSpec("retained_cum", "Нераспределённая прибыль, накопительно", mode="close", flow_row="retained"),
    )
    kpis = (
        KpiSpec("rev", "Выручка", ("rev",), POLARITY_INCOME),
        KpiSpec("opex", "Операционные расходы", ("opex",), POLARITY_EXPENSE),
        KpiSpec("ebit", "EBIT", ("ebit",), POLARITY_RESULT, ratio_row="ebit_margin"),
        KpiSpec("net", "Чистая прибыль", ("net",), POLARITY_RESULT, ratio_row="net_margin"),
    )
    chart = ChartSpec(inflow_rows=("rev",), outflow_rows=("opex", "other"), net_row="net")


class ProfessionalCashflowLayout(StatementLayout):
    report = "cashflow"
    items = (
        BalanceSpec("open", "Остаток на начало периода", mode="open", flow_row="flow"),
        SectionSpec("in", "Поступления", SECTION_REVENUE, POLARITY_INCOME, RevenueBySourceGrouping()),
        SectionSpec("out_op", "Операционные выплаты", SECTION_OPERATIONAL, POLARITY_EXPENSE, ByCategoryGrouping()),
        SectionSpec("out_other", "Прочие выплаты", SECTION_OTHER, POLARITY_EXPENSE, ByCategoryGrouping()),
        SectionSpec("out_inv", "Выплаты инвесторам", SECTION_INVEST_RETURNS, POLARITY_EXPENSE, None),
        ResultSpec(
            "flow",
            "Чистый денежный поток",
            (("in", 1), ("out_op", -1), ("out_other", -1), ("out_inv", -1)),
            strong=True,
            separator_before=True,
        ),
        BalanceSpec("close", "Остаток на конец периода", mode="close", flow_row="flow", strong=True),
    )
    kpis = (
        KpiSpec("open", "Остаток на начало", ("open",), POLARITY_RESULT),
        KpiSpec("in", "Поступления", ("in",), POLARITY_INCOME),
        KpiSpec("out", "Выплаты", ("out_op", "out_other", "out_inv"), POLARITY_EXPENSE),
        KpiSpec("close", "Остаток на конец", ("close",), POLARITY_RESULT),
    )
    chart = ChartSpec(inflow_rows=("in",), outflow_rows=("out_op", "out_other", "out_inv"), net_row="flow")
