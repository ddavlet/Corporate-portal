"""
Shared CLI options for reusable data-maintenance management commands:
tenant selection (by id or subdomain, repeatable, or --all-tenants), an
inclusive date range, and the dry-run-by-default --apply flag.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError

from apps.tenants.models import Tenant

User = get_user_model()


def add_tenant_arguments(parser) -> None:
    parser.add_argument(
        "--tenant",
        dest="tenant",
        action="append",
        help="Tenant id or subdomain. Repeatable.",
    )
    parser.add_argument(
        "--all-tenants",
        action="store_true",
        help="Process every active tenant (instead of --tenant).",
    )


def add_date_range_arguments(parser, *, what: str) -> None:
    parser.add_argument("--date-from", help=f"Only {what} on/after this date (YYYY-MM-DD).")
    parser.add_argument("--date-to", help=f"Only {what} on/before this date (YYYY-MM-DD).")


def add_apply_argument(parser) -> None:
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without this flag the command only prints a report.",
    )


def resolve_tenants(options) -> list[Tenant]:
    refs: list[str] = [str(v).strip() for v in (options.get("tenant") or []) if str(v).strip()]
    if options.get("all_tenants"):
        if refs:
            raise CommandError("Use either --tenant or --all-tenants, not both.")
        return list(Tenant.objects.filter(is_active=True).order_by("id"))
    if not refs:
        raise CommandError("Specify --tenant (id or subdomain, repeatable) or --all-tenants.")

    tenants: list[Tenant] = []
    for ref in refs:
        lookup = {"id": int(ref)} if ref.isdigit() else {"subdomain": ref}
        tenant = Tenant.objects.filter(**lookup).first()
        if tenant is None:
            raise CommandError(f"Tenant {ref!r} not found.")
        if tenant not in tenants:
            tenants.append(tenant)
    return tenants


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise CommandError(f"Invalid date {value!r}, expected YYYY-MM-DD.") from exc


def resolve_date_range(options) -> tuple[dt.date | None, dt.date | None]:
    date_from = parse_date(options.get("date_from"))
    date_to = parse_date(options.get("date_to"))
    if date_from and date_to and date_from > date_to:
        raise CommandError(f"--date-from ({date_from}) must not be after --date-to ({date_to}).")
    return date_from, date_to


def date_to_payed_at(value: dt.date) -> int:
    """Request.payed_at is stored as an int YYYYMMDD (see approval_workflow)."""
    return value.year * 10000 + value.month * 100 + value.day


def system_user():
    """pk=1 displays as "Система" — same account n8n_integration uses."""
    return User.objects.filter(pk=1).first()
