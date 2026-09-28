"""
Re-send approval cards that never reached the approver in Telegram.

A card is "unsent" when its approval is pending on the request's *current* step, has a
recipient, but no Telegram message was ever stored — the gateway/Telegram refused the
first send (typically the approver had not pressed /start in the bot yet) and nothing
retried it. The request then waits on a person who was never notified.

Works for any tenant / payment type / submission-date range:
  * --tenant       optional, repeatable or comma-separated ids; omitted = all tenants
  * --payment-type optional, repeatable or comma-separated; omitted = all payment types
  * --date-from / --date-to  optional, inclusive, by the request's submission date

Defaults to dry-run (lists what would be sent, no gateway calls). --apply re-runs the
regular approval routing per request and leaves a RequestComment from the system account
("Система") for every card that went out. Exits non-zero when some card still could not be
delivered, so the failure is not silent again.

Examples:
    python manage.py redispatch_unsent_approval_cards --tenant=5
    python manage.py redispatch_unsent_approval_cards --tenant=5 --date-from=2026-09-18 --date-to=2026-09-19 --apply
    python manage.py redispatch_unsent_approval_cards --tenant=5,7 --payment-type="Наличные,Платежная карта" --apply
"""

from __future__ import annotations

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError

from apps.modules.requests.approval_redispatch import (
    find_requests_with_unsent_approvals,
    redispatch_request,
)
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant


def _split_csv(values: list[str] | None) -> list[str]:
    return [part.strip() for value in (values or []) for part in value.split(",") if part.strip()]


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"Invalid date '{value}', expected YYYY-MM-DD.")


def _parse_tenant_ids(values: list[str] | None) -> list[int]:
    ids: list[int] = []
    for raw in _split_csv(values):
        try:
            ids.append(int(raw))
        except ValueError:
            raise CommandError(f"Invalid tenant id '{raw}', expected an integer.")
    missing = set(ids) - set(Tenant.objects.filter(pk__in=ids).values_list("pk", flat=True))
    if missing:
        raise CommandError(f"Tenant(s) not found: {sorted(missing)}.")
    return ids


def _parse_payment_types(values: list[str] | None) -> list[str]:
    allowed = {value for value, _label in Request.PAYMENT_TYPE_CHOICES}
    types = _split_csv(values)
    unknown = [t for t in types if t not in allowed]
    if unknown:
        raise CommandError(f"Unknown payment type(s) {unknown}. Allowed: {sorted(allowed)}.")
    return types


class Command(BaseCommand):
    help = (
        "Find requests waiting on an approval card that was never sent to Telegram and send it. "
        "Dry-run by default."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            action="append",
            help="Tenant id. Repeatable or comma-separated. Omit to process all tenants.",
        )
        parser.add_argument(
            "--payment-type",
            dest="payment_type",
            action="append",
            help="Payment type (e.g. Наличные). Repeatable or comma-separated. Omit to process all types.",
        )
        parser.add_argument("--date-from", help="Only requests submitted on/after this date (YYYY-MM-DD).")
        parser.add_argument("--date-to", help="Only requests submitted on/before this date (YYYY-MM-DD).")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Send the cards and leave a system comment. Without this flag only a report is printed.",
        )

    def handle(self, *args, **options):
        tenant_ids = _parse_tenant_ids(options.get("tenant"))
        payment_types = _parse_payment_types(options.get("payment_type"))
        date_from = _parse_date(options["date_from"]) if options.get("date_from") else None
        date_to = _parse_date(options["date_to"]) if options.get("date_to") else None
        if date_from and date_to and date_from > date_to:
            raise CommandError("--date-from must not be later than --date-to.")
        apply_changes: bool = options["apply"]

        found = find_requests_with_unsent_approvals(
            tenant_ids=tenant_ids, payment_types=payment_types, date_from=date_from, date_to=date_to,
        )
        if not found:
            self.stdout.write(self.style.SUCCESS("No requests with unsent approval cards found."))
            return

        if not apply_changes:
            self.stdout.write(f"Would re-send cards for {len(found)} request(s):")
            for request_obj, unsent in found:
                self.stdout.write(self._describe(request_obj, unsent))
            self.stdout.write(self.style.WARNING("Dry run complete — no cards sent. Re-run with --apply to send."))
            return

        sent_total = 0
        failed: list[str] = []
        for request_obj, unsent in found:
            outcome = redispatch_request(request_obj, unsent)
            sent_total += len(outcome.sent_approval_ids)
            if outcome.error:
                failed.append(f"Request {outcome.request_id}: error {outcome.error}")
                self.stderr.write(self.style.ERROR(f"  ! Request {outcome.request_id}: error {outcome.error}"))
            elif outcome.still_unsent:
                names = ", ".join(a.approver_user.username for a in outcome.still_unsent)
                failed.append(f"Request {outcome.request_id}: still no card for {names}")
                self.stdout.write(self.style.WARNING(
                    f"  - Request {outcome.request_id}: card NOT delivered to {names} (gateway/Telegram refused)"
                ))
            else:
                self.stdout.write(f"  + Request {outcome.request_id}: sent {len(outcome.sent_approval_ids)} card(s)")

        self.stdout.write(self.style.SUCCESS(
            f"Done. Cards sent: {sent_total}. Requests processed: {len(found)}."
        ))
        if failed:
            raise CommandError(
                f"{len(failed)} request(s) still have undelivered cards or failed:\n  " + "\n  ".join(failed)
            )

    @staticmethod
    def _describe(request_obj, unsent) -> str:
        approvers = ", ".join(f"{a.approver_user.username} (step {a.step})" for a in unsent)
        return (
            f"  + Request {request_obj.pk} [tenant {request_obj.tenant_id}, {request_obj.payment_type}, "
            f"status {request_obj.status}, submitted {request_obj.submitted_at:%Y-%m-%d}] -> {approvers}"
        )
