"""
Align request categories and payment purposes of several tenants to one list
from a JSON plan. See apps.modules.requests.payment_purpose_alignment for the
plan format and rules.

Dry-run by default; --apply writes and leaves a RequestComment from "Система"
on every request whose purpose is rewritten.

Examples:
    python manage.py align_payment_purposes --plan=lemonfit_2026_10
    python manage.py align_payment_purposes --plan=lemonfit_2026_10 --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.modules.requests.command_options import add_apply_argument
from apps.modules.requests.payment_purpose_alignment import PlanError, align_tenant, load_plan
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Align request categories and payment purposes across tenants to a JSON plan. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument(
            "--plan",
            required=True,
            help="Plan name from apps/modules/requests/purpose_alignment_plans/ (without .json) or a path.",
        )
        add_apply_argument(parser)

    def handle(self, *args, **options):
        try:
            plan = load_plan(options["plan"])
        except PlanError as exc:
            raise CommandError(str(exc)) from exc
        apply_changes: bool = options["apply"]

        tenants: list[tuple[str, Tenant]] = []
        for ref in plan.tenants:
            lookup = {"id": int(ref)} if ref.isdigit() else {"subdomain": ref}
            tenant = Tenant.objects.filter(**lookup).first()
            if tenant is None:
                raise CommandError(f"Tenant {ref!r} from the plan not found.")
            tenants.append((ref, tenant))

        total_requests = 0
        for ref, tenant in tenants:
            report = align_tenant(tenant=tenant, tenant_ref=ref, plan=plan, apply_changes=apply_changes)
            total_requests += report.requests_rewritten
            self.stdout.write(self.style.SUCCESS(
                f"[{tenant.id} {tenant.subdomain} — {tenant.name}] "
                f"{'Changes' if apply_changes else 'Would change'}: {len(report.changes)}, "
                f"requests rewritten: {report.requests_rewritten}"
            ))
            for line in report.changes:
                self.stdout.write(f"  + {line}")
            for line in report.warnings:
                self.stdout.write(self.style.WARNING(f"  ! {line}"))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Done. Rewrote {total_requests} request(s)."))
