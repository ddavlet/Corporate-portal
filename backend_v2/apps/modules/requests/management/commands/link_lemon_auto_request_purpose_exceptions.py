"""One-time: привязать назначения платежа автоматических заявок к уже созданным
исключениям согласования (RequestApprovalPurposeExceptionConfig) во всех тенантах lemon*.

Слова "Нал"/"безнал" в исходном списке назначений обозначают тип оплаты
(payment_type = "Наличные"/"Перечисление"), а не часть названия назначения —
поэтому для таких пунктов ищем оставшуюся часть строки строго под указанным
типом. Для пунктов без такого маркера тип определяется по тому, под каким(и)
RequestFormPaymentTypeConfig это назначение уже сконфигурировано (может быть
несколько — например назначение общего назначения вроде "Непредвиденные
расходы" сконфигурировано сразу под несколькими типами; тогда привязываем
исключение каждого из этих типов независимо, а не пропускаем как
неоднозначное).

Если назначения нет в справочнике "Назначения платежа" вообще
(RequestPaymentPurposeConfig), ничего не создаётся — команда только показывает,
есть ли автоматическая заявка (AutoRequestTemplate) с таким payment_purpose и
какой у неё payment_type, чтобы можно было решить, что делать, отдельно.

Run with --dry-run first to preview, then with --apply to write.

Examples:
    python manage.py link_lemon_auto_request_purpose_exceptions
    python manage.py link_lemon_auto_request_purpose_exceptions --apply
    python manage.py link_lemon_auto_request_purpose_exceptions --apply --tenant-prefix=lemon
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from apps.modules.requests.models import (
    AutoRequestTemplate,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant

PAYMENT_TYPE_CASH = "Наличные"
PAYMENT_TYPE_TRANSFER = "Перечисление"

# (purpose name with the "Нал "/" безнал" type-marker stripped, payment_type it
# denotes — or None when the item carries no such marker and the type must be
# resolved from whatever payment type(s) the purpose is already configured under).
PURPOSE_SPECS: list[tuple[str, str | None]] = [
    ("Транспортной расход", PAYMENT_TYPE_CASH),
    ("Инкассация", PAYMENT_TYPE_CASH),
    ("Зарплата", PAYMENT_TYPE_CASH),
    ("Аванс", PAYMENT_TYPE_CASH),
    ("Пополнение карты", None),
    ("Оплата по карте содержание клуба", None),
    ("Интернет", PAYMENT_TYPE_TRANSFER),
    ("Сотовая связь", PAYMENT_TYPE_TRANSFER),
    ("Таргет", None),
    ("Дивиденды", PAYMENT_TYPE_CASH),
    ("Выплата инвестиций", PAYMENT_TYPE_CASH),
    ("Канцелярия", None),
    ("Непредвиденные расходы", None),
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
        specs = [(_normalize(name), type_hint) for name, type_hint in PURPOSE_SPECS]

        tenants = list(Tenant.objects.filter(subdomain__istartswith=tenant_prefix).order_by("subdomain"))
        if not tenants:
            self.stdout.write(self.style.WARNING(f"No tenants found with subdomain starting with '{tenant_prefix}'."))
            return

        self.stdout.write(f"Tenants matched ({len(tenants)}): {', '.join(t.subdomain for t in tenants)}")

        created = 0
        already_linked = 0
        skipped: list[str] = []
        not_found: list[str] = []

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

            auto_templates = list(AutoRequestTemplate.objects.filter(tenant=tenant))
            auto_types_by_name: dict[str, set[str]] = {}
            for at in auto_templates:
                auto_types_by_name.setdefault(_normalize(at.payment_purpose), set()).add(at.payment_type)

            for wanted, type_hint in specs:
                all_matches = by_name.get(wanted, [])
                if type_hint:
                    matches = [m for m in all_matches if m.payment_type_config.payment_type == type_hint]
                else:
                    matches = all_matches

                if not matches:
                    label = f"'{wanted}' (payment_type={type_hint})" if type_hint else f"'{wanted}'"
                    other_types = sorted(
                        {m.payment_type_config.payment_type for m in all_matches} - ({type_hint} if type_hint else set())
                    )
                    hint_note = f" — found under other payment type(s): {', '.join(other_types)}" if other_types else ""
                    auto_types = auto_types_by_name.get(wanted)
                    if auto_types:
                        not_found.append(
                            f"[{tenant.subdomain}] payment purpose {label} not in request form config{hint_note}, "
                            f"but used by auto-request template(s) with payment_type: {', '.join(sorted(auto_types))}"
                        )
                    else:
                        not_found.append(
                            f"[{tenant.subdomain}] payment purpose {label} not found in request form config "
                            f"or in any auto-request template{hint_note}"
                        )
                    continue

                # A purpose without an explicit type marker may be configured
                # under several payment types (e.g. a generic purpose like
                # "Непредвиденные расходы") — link each occurrence to its own
                # type's exception independently.
                for purpose_config in matches:
                    payment_type = purpose_config.payment_type_config.payment_type

                    approval_payment_type_config = approval_config.payment_types.filter(
                        payment_type=payment_type
                    ).first()
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
                            f"[{tenant.subdomain}] payment purpose '{wanted}' (payment_type={payment_type}): "
                            f"no existing exception config — was expected to be pre-created"
                        )
                        continue
                    if len(exception_configs) > 1:
                        names = ", ".join(ec.name or f"#{ec.pk}" for ec in exception_configs)
                        skipped.append(
                            f"[{tenant.subdomain}] payment purpose '{wanted}' (payment_type={payment_type}): "
                            f"multiple exception configs ({names}) — resolve manually"
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
                            f"  = [{tenant.subdomain}] '{wanted}' (payment_type={payment_type}) already linked to "
                            f"exception '{exception_config.name or exception_config.pk}'"
                        )
                        continue

                    created += 1
                    self.stdout.write(
                        f"  + [{tenant.subdomain}] '{wanted}' (payment_type={payment_type}) -> exception "
                        f"'{exception_config.name or exception_config.pk}'"
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
        if not_found:
            self.stdout.write(self.style.WARNING(f"Not found in request form config ({len(not_found)}):"))
            for line in not_found:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
