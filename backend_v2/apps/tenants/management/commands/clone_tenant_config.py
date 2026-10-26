"""
Copy one tenant's configuration into another (new branch). See
apps.tenants.config_clone for what is copied and the rules.

Dry-run by default; --apply writes. Re-running only adds what is still missing.

Examples:
    python manage.py clone_tenant_config --source=lemonhavo --target=lemonnew --with-members
    python manage.py clone_tenant_config --source=7 --target=lemonnew --name="Lemonfit NEW" --with-members --apply
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.tenants.config_clone import clone_tenant_config
from apps.tenants.models import Tenant


class Command(BaseCommand):
    help = "Copy a tenant's configuration (modules, request form, approval routes, ...) into another tenant. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True, help="Source tenant id or subdomain.")
        parser.add_argument("--target", required=True, help="Target tenant subdomain.")
        parser.add_argument("--name", help="Target tenant name — creates the tenant if the subdomain does not exist.")
        parser.add_argument(
            "--with-members",
            action="store_true",
            help="Also add the source's active members with their roles (needed to keep approvers and requesters).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        ref = str(options["source"]).strip()
        source = Tenant.objects.filter(**({"id": int(ref)} if ref.isdigit() else {"subdomain": ref})).first()
        if source is None:
            raise CommandError(f"Source tenant {ref!r} not found.")
        apply_changes: bool = options["apply"]

        try:
            report = clone_tenant_config(
                source=source,
                target_subdomain=str(options["target"]).strip(),
                target_name=(options.get("name") or "").strip() or None,
                with_members=options["with_members"],
                apply_changes=apply_changes,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS(
            f"[{source.subdomain} → {report.target.subdomain}] "
            f"{'Changes' if apply_changes else 'Would change'}: {len(report.changes)}"
        ))
        for line in report.changes:
            self.stdout.write(f"  + {line}")
        for line in report.warnings:
            self.stdout.write(self.style.WARNING(f"  ! {line}"))

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
        else:
            self.stdout.write(self.style.SUCCESS("Done."))
