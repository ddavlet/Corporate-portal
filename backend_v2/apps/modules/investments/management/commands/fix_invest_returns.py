"""
Точечно исправить выплаты по инвестициям: месяц начисления, получатель, тип.
Суммы и даты не меняются, строки не удаляются. По умолчанию dry-run; --apply записывает.

Examples:
    # месяц начисления = месяц даты выплаты + 1 у выплат 125–149
    python manage.py fix_invest_returns --tenant=5 --ids=125-149 --billing-month-offset=1
    # все выплаты партнёру -> инвестору, тип «тело инвестиций»
    python manage.py fix_invest_returns --tenant=5 --recipient-from=PARTNER \
        --set-recipient=INVESTOR --set-type=PRINCIPAL --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.modules.investments.invest_return_fixes import (
    InvestReturnFixError,
    apply_invest_return_fixes,
    plan_invest_return_fixes,
)
from apps.tenants.models import Tenant


def _parse_ids(value: str | None) -> set[int] | None:
    """«125-149,200» -> {125, …, 149, 200}."""
    if not value:
        return None
    ids: set[int] = set()
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-", 1))
                if lo > hi:
                    raise ValueError
                ids.update(range(lo, hi + 1))
            else:
                ids.add(int(part))
        except ValueError as exc:
            raise CommandError(f"Неверный --ids {value!r}: ожидается «125-149,200».") from exc
    return ids


def _resolve_tenant(ref: str) -> Tenant:
    ref = str(ref).strip()
    tenant = Tenant.objects.filter(**({"id": int(ref)} if ref.isdigit() else {"subdomain": ref})).first()
    if tenant is None:
        raise CommandError(f"Tenant {ref!r} not found.")
    return tenant


class Command(BaseCommand):
    help = "Исправить месяц начисления / получателя / тип у выбранных выплат по инвестициям. Dry-run по умолчанию."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant id or subdomain.")
        parser.add_argument("--ids", help="Id выплат: «125-149,200».")
        parser.add_argument("--recipient-from", help="Только выплаты этому получателю (INVESTOR/PARTNER).")
        parser.add_argument(
            "--billing-month-offset",
            type=int,
            help="Месяц начисления = месяц даты выплаты + N (0 — тот же месяц).",
        )
        parser.add_argument("--set-recipient", help="Новый получатель (INVESTOR/PARTNER).")
        parser.add_argument("--set-type", help="Новый тип (PRINCIPAL/DIVIDEND/INTEREST/PROFIT_SHARE).")
        parser.add_argument("--apply", action="store_true", help="Записать изменения.")

    def handle(self, *args, **options):
        tenant = _resolve_tenant(options["tenant"])
        try:
            fixes = plan_invest_return_fixes(
                tenant=tenant,
                ids=_parse_ids(options.get("ids")),
                recipient_from=options.get("recipient_from"),
                billing_month_offset=options.get("billing_month_offset"),
                set_recipient=options.get("set_recipient"),
                set_type=options.get("set_type"),
            )
        except InvestReturnFixError as exc:
            raise CommandError(str(exc)) from exc

        apply_changes: bool = options["apply"]
        self.stdout.write(self.style.SUCCESS(
            f"[{tenant.subdomain}] {'Changing' if apply_changes else 'Would change'}: {len(fixes)} выплат(ы)"
        ))
        for fix in fixes:
            diff = "; ".join(f"{field}: {old} -> {new}" for field, (old, new) in fix.changes.items())
            self.stdout.write(f"  #{fix.id} {fix.date} {fix.sum} {fix.currency}: {diff}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
            return
        changed = apply_invest_return_fixes(tenant=tenant, fixes=fixes)
        self.stdout.write(self.style.SUCCESS(f"Done. Changed {changed} выплат(ы)."))
