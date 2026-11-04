"""Daily hard delete of stale AI-assistant reply chains.

Owner-approved exception to the project's no-delete rule. Scope is strictly
ChainNode and PendingConfirmation; UsageRecord and TelegramMessage are never touched.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from .config import CHAIN_TTL_DAYS
from .models import ChainNode, PendingConfirmation

logger = logging.getLogger(__name__)

MAX_PURGE_PASSES = 1000


def _delete_old_leaves(cutoff: datetime) -> int:
    """Delete old nodes with no children, one pass. Returns the ChainNode rows removed."""
    children = ChainNode.objects.filter(
        tenant_id=OuterRef("tenant_id"),
        chat_id=OuterRef("chat_id"),
        parent_message_id=OuterRef("message_id"),
    )
    leaves = ChainNode.objects.filter(created_at__lt=cutoff).filter(~Exists(children))
    _, per_model = leaves.delete()
    return per_model.get(ChainNode._meta.label, 0)


def purge_expired_chains(*, now: datetime | None = None) -> tuple[int, int]:
    """Peel dead branches (leaf by leaf) and drop old pending confirmations.

    A shared trunk survives while any branch below it is younger than the cutoff.
    Returns (deleted_nodes, deleted_pendings).
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=CHAIN_TTL_DAYS)

    deleted_nodes = 0
    for _ in range(MAX_PURGE_PASSES):
        removed = _delete_old_leaves(cutoff)
        if removed == 0:
            break
        deleted_nodes += removed
    else:
        logger.warning(
            "ai_assistant purge: reached the %s-pass cap; remaining old nodes will be peeled on the next run",
            MAX_PURGE_PASSES,
        )

    _, per_model = PendingConfirmation.objects.filter(created_at__lt=cutoff).delete()
    deleted_pendings = per_model.get(PendingConfirmation._meta.label, 0)
    return deleted_nodes, deleted_pendings
