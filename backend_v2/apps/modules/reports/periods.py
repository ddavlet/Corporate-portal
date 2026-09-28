"""Report periods → statement columns (month pack, year to date, year, last 12 months; months or quarters)."""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, replace
from datetime import date

PERIOD_MONTH = "month"
PERIOD_YTD = "ytd"
PERIOD_YEAR = "year"
PERIOD_LTM = "ltm"
GRANULARITY_MONTH = "month"
GRANULARITY_QUARTER = "quarter"
COMPARE_NONE = "none"
COMPARE_YOY = "yoy"

KIND_PERIOD = "period"
KIND_TOTAL = "total"
KIND_COMPARE = "compare"
KIND_DELTA = "delta"

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
MONTHS_FULL = (
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
)
QUARTERS = ("I", "II", "III", "IV")


@dataclass(frozen=True)
class PeriodSpec:
    kind: str
    year: int | None = None
    month: str | None = None
    granularity: str = GRANULARITY_MONTH
    compare: str = COMPARE_NONE


@dataclass(frozen=True)
class Column:
    key: str
    kind: str
    label: str
    sublabel: str = ""
    months: tuple[str, ...] = ()
    date_from: date | None = None
    date_to: date | None = None
    partial: bool = False
    before_start: bool = False
    starts_before_data: bool = False
    delta_of: tuple[str, str] | None = None


@dataclass(frozen=True)
class Comparison:
    key: str
    label: str
    date_from: date
    date_to: date
    unavailable: bool


@dataclass(frozen=True)
class ColumnSet:
    columns: tuple[Column, ...]
    main: Column
    sort_column: Column
    comparisons: tuple[Comparison, ...]
    chart_columns: tuple[Column, ...]
    spark_months: tuple[str, ...]


_MONTH_KEY = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def is_month_key(text: str) -> bool:
    """`YYYY-MM` with a real month; anything else (e.g. "2024-13" from a source) must not reach date()."""
    return bool(_MONTH_KEY.fullmatch(text))


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _parse_month(key: str) -> tuple[int, int]:
    year, month = key.split("-")
    return int(year), int(month)


def add_months(key: str, delta: int) -> str:
    year, month = _parse_month(key)
    total = year * 12 + (month - 1) + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_first_day(key: str) -> date:
    year, month = _parse_month(key)
    return date(year, month, 1)


def month_last_day(key: str) -> date:
    year, month = _parse_month(key)
    return date(year, month, calendar.monthrange(year, month)[1])


def months_between(first: str, last: str) -> list[str]:
    out: list[str] = []
    key = first
    while key <= last:
        out.append(key)
        key = add_months(key, 1)
    return out


def shift_year(d: date, years: int) -> date:
    year = d.year + years
    return date(year, d.month, min(d.day, calendar.monthrange(year, d.month)[1]))


def _mon(d: date) -> str:
    return MONTHS_SHORT[d.month - 1]


def range_label(date_from: date, date_to: date) -> str:
    full_to = date_to == month_last_day(month_key(date_to))
    if date_from.year == date_to.year and date_from.month == 1 and date_to.month == 12 and full_to:
        return str(date_from.year)
    if (date_from.year, date_from.month) == (date_to.year, date_to.month):
        return f"{_mon(date_to)} {date_to.year}" if full_to else f"1–{date_to.day} {_mon(date_to)} {date_to.year}"
    end = _mon(date_to) if full_to else f"{date_to.day} {_mon(date_to)}"
    if date_from.year == date_to.year:
        return f"{_mon(date_from)} – {end} {date_to.year}"
    return f"{_mon(date_from)} {date_from.year} – {end} {date_to.year}"


def _period_column(
    months: list[str], *, today: date, start_month: str, key: str, label: str, sublabel: str = ""
) -> Column:
    last_day = month_last_day(months[-1])
    date_to = min(last_day, today)
    return Column(
        key=key,
        kind=KIND_PERIOD,
        label=label,
        sublabel=sublabel,
        months=tuple(months),
        date_from=month_first_day(months[0]),
        date_to=date_to,
        partial=date_to < last_day,
        before_start=months[-1] < start_month,
        starts_before_data=months[0] < start_month <= months[-1],
    )


def _span_column(key: str, kind: str, label: str, months: list[str], *, date_to: date, start_month: str) -> Column:
    date_from = month_first_day(months[0])
    return Column(
        key=key,
        kind=kind,
        label=label,
        sublabel=range_label(date_from, date_to),
        months=tuple(months),
        date_from=date_from,
        date_to=date_to,
        partial=date_to < month_last_day(months[-1]),
        before_start=months[-1] < start_month,
        starts_before_data=months[0] < start_month <= months[-1],
    )


def _month_columns(months: list[str], *, today: date, start_month: str, with_year: bool) -> list[Column]:
    columns: list[Column] = []
    for key in months:
        year, month = _parse_month(key)
        column = _period_column(
            [key], today=today, start_month=start_month, key=key, label=MONTHS_SHORT[month - 1].capitalize()
        )
        if column.partial:
            column = replace(column, label=column.label + "*", sublabel=f"1–{column.date_to.day}")
        elif with_year:
            column = replace(column, sublabel=str(year))
        columns.append(column)
    return columns


def _quarter_columns(months: list[str], *, today: date, start_month: str, with_year: bool) -> list[Column]:
    groups: list[list[str]] = []
    for key in months:
        year, month = _parse_month(key)
        if groups:
            group_year, group_month = _parse_month(groups[-1][0])
            if (group_year, (group_month - 1) // 3) == (year, (month - 1) // 3):
                groups[-1].append(key)
                continue
        groups.append([key])
    columns: list[Column] = []
    for group in groups:
        year, first_month = _parse_month(group[0])
        last_month = _parse_month(group[-1])[1]
        quarter = (first_month - 1) // 3
        if len(group) == 1:
            span = MONTHS_SHORT[first_month - 1]
        else:
            span = f"{MONTHS_SHORT[first_month - 1]}–{MONTHS_SHORT[last_month - 1]}"
        column = _period_column(
            group, today=today, start_month=start_month, key=f"{year:04d}-Q{quarter + 1}", label=f"{QUARTERS[quarter]} кв."
        )
        sublabel = f"{span} {year}" if with_year else span
        if column.partial:
            sublabel += "*"
        columns.append(replace(column, sublabel=sublabel))
    return columns


def _range_months(spec: PeriodSpec, current: str) -> list[str]:
    if spec.kind == PERIOD_YTD:
        return months_between(f"{current[:4]}-01", current)
    if spec.kind == PERIOD_YEAR:
        year = spec.year or int(current[:4])
        last = current if year == int(current[:4]) else f"{year:04d}-12"
        return months_between(f"{year:04d}-01", last)
    if spec.kind == PERIOD_LTM:
        return months_between(add_months(current, -12), add_months(current, -1))
    raise ValueError(f"Unknown period kind {spec.kind!r}")


def _comparison(key: str, date_from: date, date_to: date, *, unavailable: bool) -> Comparison:
    return Comparison(
        key=key,
        label=f"к {range_label(date_from, date_to)}",
        date_from=date_from,
        date_to=date_to,
        unavailable=unavailable,
    )


def _spark_months(main: Column, start_month: str) -> tuple[str, ...]:
    end = month_key(main.date_to)
    if main.date_to < month_last_day(end):
        end = add_months(end, -1)
    first = max(add_months(end, -11), start_month)
    if first > end:
        return ()
    return tuple(months_between(first, end))


def _month_pack(month: str, *, today: date, start_month: str) -> ColumnSet:
    year, mon = _parse_month(month)
    main = _period_column([month], today=today, start_month=start_month, key=month, label=f"{MONTHS_FULL[mon - 1]} {year}")
    main = replace(main, sublabel=f"1–{main.date_to.day} · отчётный" if main.partial else "отчётный месяц")
    prev_key = add_months(month, -1)
    prev_year, prev_mon = _parse_month(prev_key)
    prev = _period_column(
        [prev_key],
        today=today,
        start_month=start_month,
        key=prev_key,
        label=f"{MONTHS_FULL[prev_mon - 1]} {prev_year}",
        sublabel="предыдущий месяц",
    )
    if main.partial:
        # Same dates as the unfinished month, so the change is not a partial month against a full one.
        prev_last = month_last_day(prev_key)
        prev_to = date(prev_year, prev_mon, min(main.date_to.day, prev_last.day))
        if prev_to < prev_last:
            prev = replace(prev, date_to=prev_to, partial=True, sublabel=f"1–{prev_to.day} · предыдущий месяц")
    year_key = add_months(month, -12)
    year_to = shift_year(main.date_to, -1) if main.partial else month_last_day(year_key)
    year_ago = Column(
        key=year_key,
        kind=KIND_PERIOD,
        label=f"{MONTHS_FULL[mon - 1]} {year - 1}",
        sublabel=f"1–{year_to.day} · год назад" if main.partial else "год назад",
        months=(year_key,),
        date_from=month_first_day(year_key),
        date_to=year_to,
        partial=main.partial,
        before_start=year_key < start_month,
    )
    ytd = _span_column(
        "ytd", KIND_TOTAL, "С начала года", months_between(f"{year:04d}-01", month),
        date_to=main.date_to, start_month=start_month,
    )
    columns = (
        main,
        prev,
        Column(key="delta_prev", kind=KIND_DELTA, label="Δ", sublabel="к пред. месяцу", delta_of=(month, prev_key)),
        year_ago,
        Column(key="delta_yoy", kind=KIND_DELTA, label="Δ", sublabel="к прошлому году", delta_of=(month, year_key)),
        ytd,
    )
    comparisons = (
        _comparison("prev", prev.date_from, prev.date_to, unavailable=prev.before_start),
        _comparison("yoy", year_ago.date_from, year_ago.date_to, unavailable=year_ago.before_start),
    )
    chart = _month_columns(
        months_between(add_months(month, -11), month), today=today, start_month=start_month, with_year=False
    )
    return ColumnSet(
        columns=columns,
        main=main,
        sort_column=ytd,
        comparisons=comparisons,
        chart_columns=tuple(chart),
        spark_months=_spark_months(main, start_month),
    )


def build_column_set(spec: PeriodSpec, *, today: date, start_month: str) -> ColumnSet:
    current = month_key(today)
    if spec.kind == PERIOD_MONTH:
        return _month_pack(spec.month or current, today=today, start_month=start_month)
    months = _range_months(spec, current)
    with_year = spec.kind == PERIOD_LTM
    if spec.granularity == GRANULARITY_QUARTER:
        period_columns = _quarter_columns(months, today=today, start_month=start_month, with_year=with_year)
    else:
        period_columns = _month_columns(months, today=today, start_month=start_month, with_year=with_year)
    total = _span_column(
        "total", KIND_TOTAL, "Итого", months, date_to=min(month_last_day(months[-1]), today), start_month=start_month
    )
    compare_months = [add_months(key, -12) for key in months]
    compare_to = shift_year(total.date_to, -1) if total.partial else month_last_day(compare_months[-1])
    columns: list[Column] = [*period_columns, total]
    if spec.compare == COMPARE_YOY:
        columns.append(
            _span_column("compare", KIND_COMPARE, "Год назад", compare_months, date_to=compare_to, start_month=start_month)
        )
        columns.append(
            Column(key="delta", kind=KIND_DELTA, label="Δ", sublabel="к прошлому году", delta_of=("total", "compare"))
        )
    yoy = _comparison("yoy", month_first_day(compare_months[0]), compare_to, unavailable=compare_months[0] < start_month)
    return ColumnSet(
        columns=tuple(columns),
        main=total,
        sort_column=total,
        comparisons=(yoy,),
        chart_columns=tuple(period_columns),
        spark_months=_spark_months(total, start_month),
    )
