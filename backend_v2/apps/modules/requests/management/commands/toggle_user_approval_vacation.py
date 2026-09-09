"""Send an approver on vacation, or bring them back.

While on vacation, the user's mandatory (`serial`) approval steps for the
given tenant are switched to `notification` — requests keep moving without
waiting on someone who's away, and the user still sees them (just can't
block on them). Steps already `notification` for that user are left as-is.
`payment` steps (actual payment execution) are never touched.

Run with no --apply first to preview, then with --apply to write.

--user identifies the approver by login username (most accounts here have no
email set) — pass an email and it's matched too, as a convenience for the
handful of accounts that do have one.

Examples:
    python manage.py toggle_user_approval_vacation --tenant=3 --user=s.davletyarov --action=start
    python manage.py toggle_user_approval_vacation --tenant=3 --user=s.davletyarov --action=start --apply
    python manage.py toggle_user_approval_vacation --tenant=3 --user=s.davletyarov --action=end --apply
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.modules.requests.user_approval_vacation import (
    NoActiveVacation,
    VacationAlreadyActive,
    end_vacation,
    plan_vacation_start,
    start_vacation,
)
from apps.tenants.models import Tenant

User = get_user_model()


class Command(BaseCommand):
    help = "Send a request approver on vacation (serial -> notification) or bring them back."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", type=int, required=True, help="Tenant ID.")
        parser.add_argument("--user", type=str, required=True, help="Approver's login username (or email).")
        parser.add_argument("--action", choices=["start", "end"], required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        try:
            tenant = Tenant.objects.get(pk=options["tenant"])
        except Tenant.DoesNotExist as exc:
            raise CommandError(f"Tenant {options['tenant']} not found.") from exc
        try:
            user = User.objects.get(Q(username=options["user"]) | Q(email__iexact=options["user"]))
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{options['user']}' not found (matched by username or email).") from exc
        except User.MultipleObjectsReturned as exc:
            raise CommandError(f"Multiple users match '{options['user']}' — pass the exact username.") from exc

        if options["action"] == "start":
            self._handle_start(tenant=tenant, user=user, apply_changes=apply_changes)
        else:
            self._handle_end(tenant=tenant, user=user, apply_changes=apply_changes)

    def _handle_start(self, *, tenant, user, apply_changes: bool):
        if not apply_changes:
            plan = plan_vacation_start(tenant=tenant, user=user)
            self._report_start(plan)
            self.stdout.write(self.style.WARNING("Dry run complete — re-run with --apply to write."))
            return

        try:
            _vacation, plan = start_vacation(tenant=tenant, user=user)
        except VacationAlreadyActive as exc:
            raise CommandError(str(exc)) from exc

        self._report_start(plan)
        self.stdout.write(self.style.SUCCESS(f"Отпуск начат: {user.username} в тенанте '{tenant.subdomain}'."))

    def _handle_end(self, *, tenant, user, apply_changes: bool):
        if not apply_changes:
            self.stdout.write(
                "Dry run: --action=end ничего не показывает заранее — снапшот известен только на момент возврата. "
                "Запустите с --apply, чтобы восстановить и увидеть отчёт."
            )
            return

        try:
            _vacation, result = end_vacation(tenant=tenant, user=user)
        except NoActiveVacation as exc:
            raise CommandError(str(exc)) from exc

        if result.restored:
            self.stdout.write(f"Восстановлено в 'согласование' ({len(result.restored)}):")
            for ref in result.restored:
                self.stdout.write(f"  = {ref.label}")
        if result.skipped_changed:
            self.stdout.write(
                self.style.WARNING(
                    f"Пропущено, т.к. уже не 'уведомление' (изменено вручную во время отпуска) "
                    f"({len(result.skipped_changed)}):"
                )
            )
            for ref in result.skipped_changed:
                self.stdout.write(f"  ! {ref.label}")

        self.stdout.write(self.style.SUCCESS(f"Отпуск завершён: {user.username} в тенанте '{tenant.subdomain}'."))

    def _report_start(self, plan):
        if plan.to_notify:
            self.stdout.write(f"Согласование -> уведомление ({len(plan.to_notify)}):")
            for ref in plan.to_notify:
                self.stdout.write(f"  + {ref.label}")
        if plan.already_notification:
            self.stdout.write(f"Уже было 'уведомление', не трогаем ({len(plan.already_notification)}):")
            for ref in plan.already_notification:
                self.stdout.write(f"  = {ref.label}")
        if plan.skipped_payment:
            self.stdout.write(f"Шаг исполнения платежа, не трогаем ({len(plan.skipped_payment)}):")
            for ref in plan.skipped_payment:
                self.stdout.write(f"  ~ {ref.label}")
        if not (plan.to_notify or plan.already_notification or plan.skipped_payment):
            self.stdout.write(self.style.WARNING("Пользователь не является согласующим ни в одном шаге этого тенанта."))
