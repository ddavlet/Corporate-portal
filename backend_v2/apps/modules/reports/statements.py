"""Statement engine: ledger entries + layout + columns → rows, deltas, headline numbers and chart."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from collections.abc import Iterator
from typing import Any

from apps.modules.reports.layouts import (
    POLARITY_RESULT,
    BalanceSpec,
    KpiSpec,
    RatioSpec,
    ResultSpec,
    SectionSpec,
    StatementLayout,
)
from apps.modules.reports.ledger import LedgerEntry
from apps.modules.reports.periods import KIND_DELTA, Column, ColumnSet, month_first_day, month_last_day

ZERO = Decimal("0")
MONEY = Decimal("0.01")
RATIO = Decimal("0.0001")
POINTS = Decimal("0.1")

ROW_GROUP = "group"
ROW_LINE = "line"
ROW_RESULT = "result"
ROW_RATIO = "ratio"
ROW_BALANCE = "balance"


@dataclass
class LineNode:
    id: str
    label: str
    parent: str | None
    section: SectionSpec
    children: list[str] = field(default_factory=list)


@dataclass
class LineIndex:
    nodes: dict[str, LineNode]
    entry_leaf: dict[str, str]

    def is_under(self, node_id: str, ancestor_id: str) -> bool:
        return node_id == ancestor_id or node_id.startswith(ancestor_id + ".")


def build_line_index(entries: list[LedgerEntry], layout: StatementLayout) -> LineIndex:
    nodes: dict[str, LineNode] = {}
    entry_leaf: dict[str, str] = {}
    by_section = {spec.ledger_section: spec for spec in layout.sections()}
    for spec in layout.sections():
        nodes[spec.id] = LineNode(id=spec.id, label=spec.label, parent=None, section=spec)
    for entry in entries:
        spec = by_section.get(entry.section)
        if spec is None:
            continue
        parent_id = spec.id
        if spec.grouping is not None:
            for part, label in spec.grouping.path(entry):
                node_id = f"{parent_id}.{part}"
                if node_id not in nodes:
                    nodes[node_id] = LineNode(id=node_id, label=label, parent=parent_id, section=spec)
                    nodes[parent_id].children.append(node_id)
                parent_id = node_id
        entry_leaf[entry.entry_id] = parent_id
    return LineIndex(nodes=nodes, entry_leaf=entry_leaf)


def filter_entries(
    entries: list[LedgerEntry], index: LineIndex, line_id: str | None, date_from: date, date_to: date
) -> list[LedgerEntry]:
    """Exactly the entries behind a statement cell (no line: behind every section): same leaf assignment and dates."""
    return [
        entry
        for entry, leaf in entries_in_range(entries, index, date_from, date_to)
        if line_id is None or index.is_under(leaf, line_id)
    ]


def entries_in_range(
    entries: list[LedgerEntry], index: LineIndex, date_from: date, date_to: date
) -> Iterator[tuple[LedgerEntry, str]]:
    """Entries dated within [date_from, date_to] that sit on a line of the layout, with that line's leaf id."""
    for entry in entries:
        if not (date_from <= entry.date <= date_to):
            continue
        leaf = index.entry_leaf.get(entry.entry_id)
        if leaf is not None:
            yield entry, leaf


@dataclass
class StatementRow:
    id: str
    parent: str | None
    kind: str
    label: str
    polarity: str
    depth: int
    drillable: bool
    strong: bool = False
    hint: str = ""
    separator_before: bool = False
    values: dict[str, Decimal | None] = field(default_factory=dict)
    deltas: dict[str, dict[str, Decimal] | None] = field(default_factory=dict)


@dataclass
class KpiComparison:
    key: str
    label: str
    value: Decimal | None
    delta_pct: Decimal | None


@dataclass
class Kpi:
    id: str
    label: str
    polarity: str
    value: Decimal | None
    ratio: Decimal | None
    comparisons: list[KpiComparison]
    spark: list[Decimal | None]


@dataclass
class Statement:
    report: str
    columns: tuple[Column, ...]
    rows: list[StatementRow]
    kpis: list[Kpi]
    chart: dict[str, list[Any]]


def _pct(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == ZERO:
        return None
    return ((current - previous) / abs(previous)).quantize(RATIO)


def _delta(kind: str, current: Decimal | None, previous: Decimal | None) -> dict[str, Decimal] | None:
    if current is None or previous is None:
        return None
    if kind == ROW_RATIO:
        return {"pp": ((current - previous) * 100).quantize(POINTS)}
    pct = _pct(current, previous)
    return None if pct is None else {"pct": pct}


class _StatementBuilder:
    def __init__(
        self,
        *,
        entries: list[LedgerEntry],
        layout: StatementLayout,
        column_set: ColumnSet,
        opening_balance: Decimal,
        start_month: str,
    ) -> None:
        self.entries = entries
        self.layout = layout
        self.column_set = column_set
        self.opening = opening_balance
        self.start_day = month_first_day(start_month)
        self.index = build_line_index(entries, layout)
        self.results = {item.id: item for item in layout.items if isinstance(item, ResultSpec)}
        self.ratios = {item.id: item for item in layout.items if isinstance(item, RatioSpec)}
        self.balances = {item.id: item for item in layout.items if isinstance(item, BalanceSpec)}
        self._sums_cache: dict[tuple[date, date], dict[str, Decimal]] = {}

    def sums(self, date_from: date, date_to: date) -> dict[str, Decimal]:
        key = (date_from, date_to)
        cached = self._sums_cache.get(key)
        if cached is not None:
            return cached
        sums: dict[str, Decimal] = {}
        for entry, leaf in entries_in_range(self.entries, self.index, date_from, date_to):
            node_id: str | None = leaf
            while node_id is not None:
                sums[node_id] = sums.get(node_id, ZERO) + entry.amount
                node_id = self.index.nodes[node_id].parent
        self._sums_cache[key] = sums
        return sums

    def value(self, row_id: str, date_from: date, date_to: date) -> Decimal:
        balance = self.balances.get(row_id)
        if balance is not None:
            return self.balance(balance, date_from, date_to)
        result = self.results.get(row_id)
        if result is not None:
            return sum((sign * self.value(term, date_from, date_to) for term, sign in result.terms), start=ZERO)
        return self.sums(date_from, date_to).get(row_id, ZERO)

    def ratio(self, spec: RatioSpec, date_from: date, date_to: date) -> Decimal | None:
        denominator = self.value(spec.denominator, date_from, date_to)
        if denominator == ZERO:
            return None
        return (self.value(spec.numerator, date_from, date_to) / denominator).quantize(RATIO)

    def balance(self, spec: BalanceSpec, date_from: date, date_to: date) -> Decimal:
        end = date_from - timedelta(days=1) if spec.mode == "open" else date_to
        if end < self.start_day:
            return self.opening
        return self.opening + self.value(spec.flow_row, self.start_day, end)

    def build(self) -> Statement:
        value_columns = [column for column in self.column_set.columns if column.kind != KIND_DELTA]
        rows: list[StatementRow] = []
        for item in self.layout.items:
            if isinstance(item, SectionSpec):
                rows.extend(self._section_rows(item, value_columns))
            elif isinstance(item, ResultSpec):
                rows.append(
                    self._row(
                        item.id, None, ROW_RESULT, item.label, POLARITY_RESULT, 0, value_columns,
                        strong=item.strong, hint=item.hint, separator_before=item.separator_before,
                    )
                )
            elif isinstance(item, RatioSpec):
                values = {
                    c.key: None if c.before_start else self.ratio(item, c.date_from, c.date_to) for c in value_columns
                }
                rows.append(
                    StatementRow(
                        id=item.id, parent=None, kind=ROW_RATIO, label=item.label, polarity=POLARITY_RESULT,
                        depth=1, drillable=False, values=values,
                    )
                )
            elif isinstance(item, BalanceSpec):
                rows.append(
                    self._row(item.id, None, ROW_BALANCE, item.label, POLARITY_RESULT, 0, value_columns, strong=item.strong)
                )
        self._fill_deltas(rows)
        return Statement(
            report=self.layout.report,
            columns=self.column_set.columns,
            rows=rows,
            kpis=[self._kpi(spec) for spec in self.layout.kpis],
            chart=self._chart(),
        )

    def _row(
        self,
        row_id: str,
        parent: str | None,
        kind: str,
        label: str,
        polarity: str,
        depth: int,
        columns: list[Column],
        *,
        drillable: bool = False,
        strong: bool = False,
        hint: str = "",
        separator_before: bool = False,
    ) -> StatementRow:
        values = {c.key: None if c.before_start else self.value(row_id, c.date_from, c.date_to) for c in columns}
        return StatementRow(
            id=row_id, parent=parent, kind=kind, label=label, polarity=polarity, depth=depth,
            drillable=drillable, strong=strong, hint=hint, separator_before=separator_before, values=values,
        )

    def _section_rows(self, spec: SectionSpec, columns: list[Column]) -> list[StatementRow]:
        sort_column = self.column_set.sort_column
        sort_sums = self.sums(sort_column.date_from, sort_column.date_to)
        fixed = spec.grouping.fixed_order if spec.grouping else ()
        rows: list[StatementRow] = []

        def visible(node_id: str) -> bool:
            return any(
                not c.before_start and self.sums(c.date_from, c.date_to).get(node_id, ZERO) != ZERO for c in columns
            )

        def order(node_id: str) -> tuple[int, int, Decimal, str]:
            part = node_id.rsplit(".", 1)[-1]
            if part in fixed:
                return (0, fixed.index(part), ZERO, "")
            return (1, 0, -sort_sums.get(node_id, ZERO), self.index.nodes[node_id].label)

        def visit(node_id: str, depth: int) -> None:
            node = self.index.nodes[node_id]
            children = sorted((child for child in node.children if visible(child)), key=order)
            rows.append(
                self._row(
                    node_id, node.parent, ROW_GROUP if children else ROW_LINE, node.label, spec.polarity, depth,
                    columns, drillable=True, separator_before=spec.separator_before and depth == 0,
                )
            )
            for child in children:
                visit(child, depth + 1)

        visit(spec.id, 0)
        return rows

    def _fill_deltas(self, rows: list[StatementRow]) -> None:
        by_key = {column.key: column for column in self.column_set.columns}
        for column in self.column_set.columns:
            if column.kind != KIND_DELTA or column.delta_of is None:
                continue
            a_key, b_key = column.delta_of
            unusable = any(by_key[key].before_start or by_key[key].starts_before_data for key in (a_key, b_key))
            for row in rows:
                row.deltas[column.key] = (
                    None if unusable else _delta(row.kind, row.values.get(a_key), row.values.get(b_key))
                )

    def _kpi_value(self, spec: KpiSpec, date_from: date, date_to: date) -> Decimal:
        return sum((self.value(row_id, date_from, date_to) for row_id in spec.rows), start=ZERO)

    def _kpi(self, spec: KpiSpec) -> Kpi:
        main = self.column_set.main
        value = None if main.before_start else self._kpi_value(spec, main.date_from, main.date_to)
        ratio_spec = self.ratios.get(spec.ratio_row) if spec.ratio_row else None
        ratio = None if main.before_start or ratio_spec is None else self.ratio(ratio_spec, main.date_from, main.date_to)
        comparisons: list[KpiComparison] = []
        for comparison in self.column_set.comparisons:
            other = None if comparison.unavailable else self._kpi_value(spec, comparison.date_from, comparison.date_to)
            comparisons.append(
                KpiComparison(key=comparison.key, label=comparison.label, value=other, delta_pct=_pct(value, other))
            )
        spark = [self._kpi_value(spec, month_first_day(key), month_last_day(key)) for key in self.column_set.spark_months]
        return Kpi(
            id=spec.id, label=spec.label, polarity=spec.polarity, value=value, ratio=ratio,
            comparisons=comparisons, spark=spark,
        )

    def _chart(self) -> dict[str, list[Any]]:
        spec = self.layout.chart
        chart: dict[str, list[Any]] = {"labels": [], "partial": [], "inflow": [], "outflow": [], "net": []}
        for column in self.column_set.chart_columns:
            chart["labels"].append(column.label)
            chart["partial"].append(column.partial)
            if column.before_start:
                for series in ("inflow", "outflow", "net"):
                    chart[series].append(None)
                continue
            chart["inflow"].append(
                sum((self.value(r, column.date_from, column.date_to) for r in spec.inflow_rows), start=ZERO)
            )
            chart["outflow"].append(
                sum((self.value(r, column.date_from, column.date_to) for r in spec.outflow_rows), start=ZERO)
            )
            chart["net"].append(self.value(spec.net_row, column.date_from, column.date_to))
        return chart


def build_statement(
    *,
    entries: list[LedgerEntry],
    layout: StatementLayout,
    column_set: ColumnSet,
    opening_balance: Decimal,
    start_month: str,
) -> Statement:
    return _StatementBuilder(
        entries=entries,
        layout=layout,
        column_set=column_set,
        opening_balance=opening_balance,
        start_month=start_month,
    ).build()


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(MONEY))


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def column_to_dict(column: Column) -> dict[str, Any]:
    return {
        "key": column.key,
        "kind": column.kind,
        "label": column.label,
        "sublabel": column.sublabel,
        "months": list(column.months),
        "from": column.date_from.isoformat() if column.date_from else None,
        "to": column.date_to.isoformat() if column.date_to else None,
        "partial": column.partial,
        "before_start": column.before_start,
        "starts_before_data": column.starts_before_data,
        "delta_of": list(column.delta_of) if column.delta_of else None,
    }


def _row_to_dict(row: StatementRow) -> dict[str, Any]:
    render = _plain if row.kind == ROW_RATIO else _money
    return {
        "id": row.id,
        "parent": row.parent,
        "kind": row.kind,
        "label": row.label,
        "polarity": row.polarity,
        "depth": row.depth,
        "drillable": row.drillable,
        "strong": row.strong,
        "hint": row.hint,
        "separator_before": row.separator_before,
        "values": {key: render(value) for key, value in row.values.items()},
        "deltas": {
            key: None if delta is None else {name: str(value) for name, value in delta.items()}
            for key, delta in row.deltas.items()
        },
    }


def statement_to_dict(statement: Statement) -> dict[str, Any]:
    chart = statement.chart
    return {
        "report": statement.report,
        "columns": [column_to_dict(column) for column in statement.columns],
        "rows": [_row_to_dict(row) for row in statement.rows],
        "kpis": [
            {
                "id": kpi.id,
                "label": kpi.label,
                "polarity": kpi.polarity,
                "value": _money(kpi.value),
                "ratio": _plain(kpi.ratio),
                "comparisons": [
                    {"key": c.key, "label": c.label, "value": _money(c.value), "delta_pct": _plain(c.delta_pct)}
                    for c in kpi.comparisons
                ],
                "spark": [_money(value) for value in kpi.spark],
            }
            for kpi in statement.kpis
        ],
        "chart": {
            "labels": chart["labels"],
            "partial": chart["partial"],
            "inflow": [_money(v) for v in chart["inflow"]],
            "outflow": [_money(v) for v in chart["outflow"]],
            "net": [_money(v) for v in chart["net"]],
        },
    }
