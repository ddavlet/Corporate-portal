"""Signal handlers for the investments module."""

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.modules.investments.models import InvestReturn, ProjectInvestment

logger = logging.getLogger(__name__)


def _recompute_linked_schedule(schedule_id) -> None:
    """Recompute the paid status of the schedule a payout belongs to.

    Kept out of the approval state machine on purpose (OCP): the routing code only flips
    ``InvestReturn.confirmed`` and saves it — the rollup into the schedule's payment_amount /
    is_paid happens here, so new payout sources stay in sync without touching that logic.
    """
    if not schedule_id:
        return
    from apps.modules.investments.models import InvestPayoutSchedule
    from apps.modules.investments.notification_services import recompute_payout_schedule_paid_status

    schedule = InvestPayoutSchedule.objects.filter(pk=schedule_id).first()
    if schedule is not None:
        recompute_payout_schedule_paid_status(schedule=schedule)


@receiver(post_save, sender=InvestReturn, dispatch_uid="investments_recompute_schedule_on_return_save")
def recompute_schedule_on_return_save(sender, instance, **kwargs):
    # Skip raw fixture loads: related rows may not exist yet and serialized state is authoritative.
    if kwargs.get("raw"):
        return
    _recompute_linked_schedule(instance.payout_schedule_id)


@receiver(post_delete, sender=InvestReturn, dispatch_uid="investments_recompute_schedule_on_return_delete")
def recompute_schedule_on_return_delete(sender, instance, **kwargs):
    _recompute_linked_schedule(instance.payout_schedule_id)


@receiver(post_save, sender=ProjectInvestment, dispatch_uid="investments_ensure_cash_revenue_on_investment_save")
def ensure_cash_revenue_on_investment_save(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    from apps.modules.investments.funding_revenue import ensure_investor_cash_revenue

    try:
        ensure_investor_cash_revenue(project_investment=instance)
    except Exception:
        # Пробрасываем: подтверждение идёт в transaction.atomic() и откатится целиком.
        logger.exception("Failed to create investor cash revenue for project investment %s", instance.pk)
        raise
