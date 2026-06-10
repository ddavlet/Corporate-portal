"""Soft-delete expired draft requests after a retention period."""

from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone

from apps.modules.requests.models import Request

logger = logging.getLogger(__name__)

DRAFT_RETENTION_DAYS = 10


def purge_expired_draft_requests(*, now_dt: dt.datetime | None = None) -> int:
    """
    Mark DRAFT requests older than DRAFT_RETENTION_DAYS as DELETED.

    Uses soft delete (status=DELETED) so rows stay in DB but disappear from portal/API.
    """
    now_dt = now_dt or timezone.now()
    cutoff = now_dt - dt.timedelta(days=DRAFT_RETENTION_DAYS)
    qs = Request.all_objects.filter(status=Request.STATUS_DRAFT, created_at__lt=cutoff)
    updated = qs.update(status=Request.STATUS_DELETED)
    if updated:
        logger.info("Marked %s expired draft request(s) as DELETED (cutoff=%s)", updated, cutoff.isoformat())
    return updated
