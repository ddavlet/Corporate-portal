"""Signal handlers for the investments module."""

import logging

from django.db.models.signals import post_delete, post_save, pre_save
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


# Атрибут экземпляра: значение `confirmed` в БД до текущего save (None — строки ещё не было).
_PREVIOUS_CONFIRMED_ATTR = "_funding_previous_confirmed"


@receiver(pre_save, sender=ProjectInvestment, dispatch_uid="investments_track_confirmed_before_save")
def track_confirmed_before_save(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    previous = None
    # Переход False→True возможен только когда сохраняется confirmed=True у существующей строки.
    if instance.pk is not None and instance.confirmed:
        previous = (
            ProjectInvestment.objects.filter(pk=instance.pk).values_list("confirmed", flat=True).first()
        )
    setattr(instance, _PREVIOUS_CONFIRMED_ATTR, previous)


def _is_confirmation_transition(instance, *, created: bool, update_fields) -> bool:
    previous = instance.__dict__.pop(_PREVIOUS_CONFIRMED_ATTR, None)
    if created or not instance.confirmed:
        return False
    if update_fields is not None and "confirmed" not in update_fields:
        return False
    return previous is False


@receiver(post_save, sender=ProjectInvestment, dispatch_uid="investments_ensure_cash_revenue_on_investment_save")
def ensure_cash_revenue_on_investment_save(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    # Приход создаётся только при подтверждении (False→True). Строка, созданная сразу подтверждённой
    # (импорт n8n), и пересохранение уже подтверждённого вложения прихода не создают.
    if not _is_confirmation_transition(
        instance, created=bool(kwargs.get("created")), update_fields=kwargs.get("update_fields")
    ):
        return
    from apps.modules.investments.funding_revenue import ensure_investor_cash_revenue

    try:
        ensure_investor_cash_revenue(project_investment=instance)
    except Exception:
        # Пробрасываем: подтверждение идёт в transaction.atomic() и откатится целиком.
        logger.exception("Failed to create investor cash revenue for project investment %s", instance.pk)
        raise
