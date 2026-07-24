"""One-time: привязать назначения платежа автоматических заявок к уже созданным
исключениям согласования (RequestApprovalPurposeExceptionConfig) во всех тенантах lemon*.

Тип оплаты для каждого назначения определяется по уже настроенному
RequestPaymentPurposeConfig этого тенанта (не по эвристике из названия) — так
результат не зависит от того, что название начинается на "Нал"/"безнал"/итд.

Run with --dry-run first to preview, then with --apply to write.

Examples:
    python manage.py link_lemon_auto_request_purpose_exceptions --dry-run
    python manage.py link_lemon_auto_request_purpose_exceptions --apply
    python manage.py link_lemon_auto_request_purpose_exceptions --apply --tenant-prefix=lemon
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from apps.modules.requests.models import (
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant

PURPOSE_NAMES = [
    "Нал Транспортной расход",
    "Нал Инкассация",
    "Нал Зарплата",
    "Нал Аванс",
    "Пополнение карты",
    "Оплата по карте содержание клуба",
    "Интернет безнал",
    "Сотовая связь безнал",
    "Таргет",
    "Дивиденды нал",
    "Выплата инвестиций нал",
    "Канцелярия",
    "Непредвиденные расходы",
]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


class Command(BaseCommand):
    help = (
        "Backfill: link auto-request payment purposes to already-created "
        "RequestApprovalPurposeExceptionConfig for tenants matching --tenant-prefix (one-time)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )
        parser.add_argument(
            "--tenant-prefix",
            default="lemon",
            help="Case-insensitive subdomain prefix used to select tenants (default: lemon).",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenant_prefix: str = options["tenant_prefix"]
        wanted_names = {_normalize(name) for name in PURPOSE_NAMES}

        tenants = list(Tenant.objects.filter(subdomain__istartswith=tenant_prefix).order_by("subdomain"))
        if not tenants:
            self.stdout.write(self.style.WARNING(f"No tenants found with subdomain starting with '{tenant_prefix}'."))
            return

        self.stdout.write(f"Tenants matched ({len(tenants)}): {', '.join(t.subdomain for t in tenants)}")

        created = 0
        already_linked = 0
        skipped: list[str] = []

        for tenant in tenants:
            approval_config = getattr(tenant, "request_approval_config", None)
            if approval_config is None:
                skipped.append(f"[{tenant.subdomain}] no RequestApprovalConfig — skipped entirely")
                continue

            form_config = getattr(tenant, "request_form_config", None)
            if form_config is None:
                skipped.append(f"[{tenant.subdomain}] no RequestFormConfig — skipped entirely")
                continue

            purpose_configs = list(
                RequestPaymentPurposeConfig.objects.filter(
                    payment_type_config__config=form_config,
                ).select_related("payment_type_config")
            )
            by_name: dict[str, list[RequestPaymentPurposeConfig]] = {}
            for pc in purpose_configs:
                by_name.setdefault(_normalize(pc.name), []).append(pc)

            for wanted in wanted_names:
                matches = by_name.get(wanted, [])
                if not matches:
                    skipped.append(f"[{tenant.subdomain}] payment purpose '{wanted}' not found in request form config")
                    continue
                if len(matches) > 1:
                    types = ", ".join(sorted({m.payment_type_config.payment_type for m in matches}))
                    skipped.append(
                        f"[{tenant.subdomain}] payment purpose '{wanted}' is ambiguous "
                        f"(exists under multiple payment types: {types}) — resolve manually"
                    )
                    continue

                purpose_config = matches[0]
                payment_type = purpose_config.payment_type_config.payment_type

                approval_payment_type_config = approval_config.payment_types.filter(payment_type=payment_type).first()
                if approval_payment_type_config is None:
                    skipped.append(
                        f"[{tenant.subdomain}] payment purpose '{wanted}': no approval config for "
                        f"payment_type '{payment_type}'"
                    )
                    continue

                exception_configs = list(
                    RequestApprovalPurposeExceptionConfig.objects.filter(
                        payment_type_config=approval_payment_type_config,
                    )
                )
                if not exception_configs:
                    skipped.append(
                        f"[{tenant.subdomain}] payment purpose '{wanted}': no existing exception config for "
                        f"payment_type '{payment_type}' — was expected to be pre-created"
                    )
                    continue
                if len(exception_configs) > 1:
                    names = ", ".join(ec.name or f"#{ec.pk}" for ec in exception_configs)
                    skipped.append(
                        f"[{tenant.subdomain}] payment purpose '{wanted}': multiple exception configs for "
                        f"payment_type '{payment_type}' ({names}) — resolve manually"
                    )
                    continue

                exception_config = exception_configs[0]
                exists = RequestApprovalPurposeExceptionPurpose.objects.filter(
                    payment_type_config=approval_payment_type_config,
                    payment_purpose=purpose_config,
                ).first()
                if exists is not None:
                    already_linked += 1
                    self.stdout.write(
                        f"  = [{tenant.subdomain}] '{wanted}' already linked to exception "
                        f"'{exception_config.name or exception_config.pk}'"
                    )
                    continue

                created += 1
                self.stdout.write(
                    f"  + [{tenant.subdomain}] '{wanted}' -> exception "
                    f"'{exception_config.name or exception_config.pk}' (payment_type={payment_type})"
                )
                if apply_changes:
                    RequestApprovalPurposeExceptionPurpose.objects.create(
                        exception_config=exception_config,
                        payment_type_config=approval_payment_type_config,
                        payment_purpose=purpose_config,
                    )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Created' if apply_changes else 'Would create'}: {created}"))
        self.stdout.write(f"Already linked: {already_linked}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
