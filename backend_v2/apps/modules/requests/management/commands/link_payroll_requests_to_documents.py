"""
Link PAYED "Начисление ЗП" заявки to explicitly given payroll documents.
See apps.modules.requests.payroll_request_document_linking for the rules.

Dry-run by default; --apply writes and leaves a RequestComment from "Система".

Examples:
    python manage.py link_payroll_requests_to_documents --tenant=lemonfit \
        --pair 7226:1-000000077 --pair 7585:1-000000084
    python manage.py link_payroll_requests_to_documents --tenant=lemonfit \
        --pair 7163:1-000000073 --set-amount-from-document --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.modules.requests.command_options import add_apply_argument, resolve_tenants
from apps.modules.requests.payroll_request_document_linking import link_payroll_requests_to_documents


def _parse_pair(raw: str) -> tuple[int, str]:
    request_part, sep, doc_part = raw.partition(":")
    if not sep or not request_part.strip().isdigit() or not doc_part.strip():
        raise CommandError(f"Invalid --pair {raw!r}, expected <request_id>:<doc_id>.")
    return int(request_part.strip()), doc_part.strip()


class Command(BaseCommand):
    help = "Link PAYED payroll заявки to explicitly given payroll documents. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True, help="Tenant id or subdomain.")
        parser.add_argument(
            "--pair", action="append", required=True, help="<request_id>:<payroll doc_id>. Repeatable.",
        )
        parser.add_argument(
            "--set-amount-from-document",
            action="store_true",
            help="When the request amount differs from the document total, replace it with the total.",
        )
        add_apply_argument(parser)

    def handle(self, *args, **options):
        (tenant,) = resolve_tenants({"tenant": [options["tenant"]]})
        pairs = [_parse_pair(raw) for raw in options["pair"]]
        apply_changes: bool = options["apply"]

        outcomes = link_payroll_requests_to_documents(
            tenant=tenant,
            pairs=pairs,
            set_amount_from_document=options["set_amount_from_document"],
            apply_changes=apply_changes,
        )
        linked = [o for o in outcomes if o.outcome != "error"]
        self.stdout.write(self.style.SUCCESS(
            f"[{tenant.subdomain}] {'Linked' if apply_changes else 'Would link'}: {len(linked)}"
        ))
        for o in linked:
            amount_note = f", amount {o.old_amount} -> {o.new_amount}" if o.outcome == "linked_amount_fixed" else ""
            self.stdout.write(f"  + Request {o.request_id}: {o.detail}{amount_note}")
        for o in outcomes:
            if o.outcome == "error":
                self.stdout.write(self.style.WARNING(f"  - Request {o.request_id} -> {o.doc_id}: {o.detail}"))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Linked {len(linked)} request(s)."))
