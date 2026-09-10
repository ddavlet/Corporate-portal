"""One-time: create a single-step ("payment" / выплата) approval exception for the
"Перевод между кассами" purpose under the "Наличные" payment type, for every tenant
that already has that purpose configured (see `add_cash_register_transfer_purpose`).

The exception's one payment step copies its approver(s) and its payment_action_mode
/ telegram_chat from that tenant's existing default "Наличные" payment step — same
people who already approve regular cash payouts approve transfer payouts, just
without the earlier notification/serial steps.

Tenants without an approval exception source (no RequestApprovalConfig entry for
"Наличные", no payment step in it, or no approvers on that payment step) are
skipped — this command never invents an approver.

Run with no flags first to preview, then with --apply to write.

Examples:
    python manage.py add_cash_register_transfer_approval_exception
    python manage.py add_cash_register_transfer_approval_exception --apply
    python manage.py add_cash_register_transfer_approval_exception --apply --tenant=1
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestApprovalPurposeExceptionStepApproverConfig,
    RequestApprovalPurposeExceptionStepConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.tenants.models import Tenant

PAYMENT_TYPE = Request.PAYMENT_TYPE_CASH
PURPOSE_NAME = "Перевод между кассами"


class Command(BaseCommand):
    help = (
        "Backfill: create a single payment-step approval exception for the "
        "'Перевод между кассами' purpose under 'Наличные', reusing each tenant's "
        "existing payment-step approver(s) (one-time)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write changes. Without this flag the command only prints a report.",
        )
        parser.add_argument(
            "--tenant",
            type=int,
            default=None,
            help="Limit to a single tenant id (default: all tenants).",
        )

    def handle(self, *args, **options):
        apply_changes: bool = options["apply"]
        tenant_id: int | None = options["tenant"]

        tenants = Tenant.objects.all().order_by("subdomain")
        if tenant_id is not None:
            tenants = tenants.filter(id=tenant_id)
        tenants = list(tenants)
        if not tenants:
            self.stdout.write(self.style.WARNING("No matching tenants."))
            return

        created = 0
        already_present = 0
        skipped: list[str] = []

        for tenant in tenants:
            form_config = getattr(tenant, "request_form_config", None)
            appr_config = getattr(tenant, "request_approval_config", None)
            if form_config is None or appr_config is None:
                skipped.append(f"[{tenant.subdomain}] no request form/approval config — skipped")
                continue

            form_pt_cash = RequestFormPaymentTypeConfig.objects.filter(
                config=form_config, payment_type=PAYMENT_TYPE
            ).first()
            if form_pt_cash is None:
                skipped.append(f"[{tenant.subdomain}] no '{PAYMENT_TYPE}' form config — skipped")
                continue

            purpose_cfg = RequestPaymentPurposeConfig.objects.filter(
                payment_type_config=form_pt_cash, name=PURPOSE_NAME
            ).first()
            if purpose_cfg is None:
                skipped.append(
                    f"[{tenant.subdomain}] purpose '{PURPOSE_NAME}' not configured yet "
                    "(run add_cash_register_transfer_purpose first) — skipped"
                )
                continue

            appr_pt_cash = RequestApprovalPaymentTypeConfig.objects.filter(
                config=appr_config, payment_type=PAYMENT_TYPE
            ).first()
            if appr_pt_cash is None:
                skipped.append(f"[{tenant.subdomain}] no '{PAYMENT_TYPE}' approval config — skipped")
                continue

            already = RequestApprovalPurposeExceptionPurpose.objects.filter(
                payment_type_config=appr_pt_cash, payment_purpose=purpose_cfg
            ).first()
            if already is not None:
                already_present += 1
                self.stdout.write(
                    f"  = [{tenant.subdomain}] already present (exception "
                    f"'{already.exception_config.name or already.exception_config_id}')"
                )
                continue

            source_step = (
                RequestApprovalStepConfig.objects.filter(
                    payment_type_config=appr_pt_cash, step_type=Approval.STEP_TYPE_PAYMENT
                )
                .order_by("step")
                .first()
            )
            if source_step is None:
                skipped.append(
                    f"[{tenant.subdomain}] default '{PAYMENT_TYPE}' flow has no payment step — "
                    "no approver to copy, skipped"
                )
                continue

            approver_ids = list(
                RequestApprovalStepApproverConfig.objects.filter(step_config=source_step).values_list(
                    "approver_user_id", flat=True
                )
            )
            if not approver_ids:
                skipped.append(
                    f"[{tenant.subdomain}] default '{PAYMENT_TYPE}' payment step has no approvers — skipped"
                )
                continue

            approver_names = list(
                RequestApprovalStepApproverConfig.objects.filter(step_config=source_step)
                .values_list("approver_user__username", flat=True)
                .order_by("approver_user__username")
            )
            created += 1
            self.stdout.write(
                f"  + [{tenant.subdomain}] would create exception with approver(s): {', '.join(approver_names)}"
            )
            if apply_changes:
                exception_config = RequestApprovalPurposeExceptionConfig.objects.create(
                    payment_type_config=appr_pt_cash, name=PURPOSE_NAME, is_enabled=True
                )
                step = RequestApprovalPurposeExceptionStepConfig.objects.create(
                    exception_config=exception_config,
                    step=1,
                    step_type=Approval.STEP_TYPE_PAYMENT,
                    is_enabled=True,
                    payment_action_mode=source_step.payment_action_mode,
                    payment_webapp_url=source_step.payment_webapp_url,
                    telegram_chat=source_step.telegram_chat,
                )
                RequestApprovalPurposeExceptionStepApproverConfig.objects.bulk_create(
                    [
                        RequestApprovalPurposeExceptionStepApproverConfig(step_config=step, approver_user_id=uid)
                        for uid in approver_ids
                    ]
                )
                RequestApprovalPurposeExceptionPurpose.objects.create(
                    exception_config=exception_config,
                    payment_type_config=appr_pt_cash,
                    payment_purpose=purpose_cfg,
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"{'Created' if apply_changes else 'Would create'}: {created}"))
        self.stdout.write(f"Already present: {already_present}")
        if skipped:
            self.stdout.write(self.style.WARNING(f"Skipped ({len(skipped)}):"))
            for line in skipped:
                self.stdout.write(f"  - {line}")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete — no changes made. Re-run with --apply to write."))
