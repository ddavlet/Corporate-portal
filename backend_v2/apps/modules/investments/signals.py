"""Signal handlers for the investments module."""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.modules.requests.models import Request


@receiver(post_save, sender=Request)
def clear_payout_schedule_link_on_request_rejection(sender, instance, **kwargs):
    """When a Request created from a payout schedule is rejected, clear the schedule's FK
    so the next poller run can resume notifications and the user can act again.

    Why filter().update() and not the reverse OneToOne: avoids the lazy RelatedObjectDoesNotExist,
    bypasses signals (no cascading post_save loop), and is a single targeted UPDATE.
    """
    if instance.status != Request.STATUS_REJECTED:
        return
    from apps.modules.investments.models import InvestPayoutSchedule

    InvestPayoutSchedule.objects.filter(created_request_id=instance.pk).update(
        created_request=None,
        last_edit_at=timezone.now(),
    )
