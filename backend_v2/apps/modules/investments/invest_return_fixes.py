"""Точечное исправление полей выплат по инвестициям (InvestReturn) — для команды fix_invest_returns.

Меняет только месяц начисления, получателя и тип у явно выбранных строк одного тенанта.
Суммы, даты и валюта не трогаются, строки не удаляются. Повторный запуск ничего не меняет:
месяц начисления считается от даты выплаты, а не от текущего значения.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db import transaction

from apps.modules.investments.billing_month_rules import add_calendar_months, month_first_day
from apps.modules.investments.models import InvestReturn


class InvestReturnFixError(ValueError):
    """Неверные параметры: строки не найдены, неизвестный получатель/тип, нечего менять."""


@dataclass(frozen=True)
class InvestReturnFix:
    id: int
    date: date
    sum: str
    currency: str
    # field -> (old, new); only fields that actually change
    changes: dict


def _choice(enum, value: str | None, *, what: str) -> str | None:
    """Value of a TextChoices member by its value («инвестор») or name (INVESTOR), case-insensitive."""
    if value is None:
        return None
    raw = str(value).strip()
    for member in enum:
        if raw == member.value or raw.upper() == member.name:
            return member.value
    allowed = ", ".join(f"{m.name}/{m.value}" for m in enum)
    raise InvestReturnFixError(f"Неизвестный {what} {raw!r}. Допустимо: {allowed}.")


def plan_invest_return_fixes(
    *,
    tenant,
    ids: set[int] | None = None,
    recipient_from: str | None = None,
    billing_month_offset: int | None = None,
    set_recipient: str | None = None,
    set_type: str | None = None,
) -> list[InvestReturnFix]:
    """
    Строки тенанта: с ``ids`` (если заданы) и с получателем ``recipient_from`` (если задан).
    ``billing_month_offset`` — месяц начисления = первый день месяца даты выплаты + N месяцев.
    """
    recipient_from = _choice(InvestReturn.Recipient, recipient_from, what="получатель")
    set_recipient = _choice(InvestReturn.Recipient, set_recipient, what="получатель")
    set_type = _choice(InvestReturn.ReturnType, set_type, what="тип")
    if not ids and recipient_from is None:
        raise InvestReturnFixError("Укажите, какие выплаты менять: ids и/или recipient_from.")
    if billing_month_offset is None and set_recipient is None and set_type is None:
        raise InvestReturnFixError("Нечего менять: укажите billing_month_offset, set_recipient или set_type.")

    qs = InvestReturn.objects.filter(tenant=tenant)
    if ids:
        found = set(qs.filter(id__in=ids).values_list("id", flat=True))
        missing = sorted(set(ids) - found)
        if missing:
            raise InvestReturnFixError(f"Выплаты не найдены в тенанте {tenant.pk}: {missing}")
        qs = qs.filter(id__in=ids)
    if recipient_from is not None:
        qs = qs.filter(recipient=recipient_from)

    fixes: list[InvestReturnFix] = []
    for row in qs.order_by("id"):
        changes = {}
        if billing_month_offset is not None:
            new_billing = add_calendar_months(month_first_day(row.date), billing_month_offset)
            if row.billing_date != new_billing:
                changes["billing_date"] = (row.billing_date, new_billing)
        if set_recipient is not None and row.recipient != set_recipient:
            changes["recipient"] = (row.recipient, set_recipient)
        if set_type is not None and row.type != set_type:
            changes["type"] = (row.type, set_type)
        if changes:
            fixes.append(
                InvestReturnFix(id=row.id, date=row.date, sum=str(row.sum), currency=row.currency, changes=changes)
            )
    return fixes


@transaction.atomic
def apply_invest_return_fixes(*, tenant, fixes: list[InvestReturnFix]) -> int:
    """Записывает изменения через save() — срабатывают сигналы пересчёта расписания."""
    rows = {r.id: r for r in InvestReturn.objects.select_for_update().filter(tenant=tenant, id__in=[f.id for f in fixes])}
    for fix in fixes:
        row = rows[fix.id]
        for field, (_old, new) in fix.changes.items():
            setattr(row, field, new)
        row.save(update_fields=[*fix.changes.keys(), "last_edit_at"])
    return len(fixes)
