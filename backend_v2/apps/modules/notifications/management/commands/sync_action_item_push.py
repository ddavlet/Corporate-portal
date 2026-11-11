"""Web Push of action items from backend_cron: the only place pushes are sent from.

Two runs, each under its own flock:
- `--requested-only` (every minute): users whose subscriptions were marked by approval hooks
  (`push_services.request_sync_for_object`), oldest request first;
- full catch-up (every 5 minutes): every user with an active subscription or an open push
  state, longest-unsynced first, so `--max-users` and `--max-seconds` never starve the tail.
  It closes paths without hooks (drafts marked DELETED by a bulk update, lost memberships)
  and retries users whose push failed.

Examples:
    python manage.py sync_action_item_push --requested-only --max-seconds 50
    python manage.py sync_action_item_push --max-users 500 --max-seconds 240
"""

from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone as dt_timezone
from time import monotonic

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Min

from apps.modules.notifications import push_services
from apps.modules.notifications.models import ActionItemPushState, PushSubscription

logger = logging.getLogger(__name__)

_NEVER = datetime.min.replace(tzinfo=dt_timezone.utc)


def candidate_user_ids(*, limit: int) -> tuple[list[int], int]:
    """Users to sync, longest-unsynced first; (first `limit`, total).

    Users with an active subscription go by the oldest `synced_at` of their devices (never
    synced first); users with only open push states (nothing to send, states to close) follow.
    """
    rows = (
        PushSubscription.objects.filter(revoked_at__isnull=True)
        .values("user_id")
        .annotate(last_synced=Min("synced_at"))
    )
    with_subscription = [
        row["user_id"]
        for row in sorted(
            rows, key=lambda r: (r["last_synced"] is not None, r["last_synced"] or _NEVER, r["user_id"])
        )
    ]
    with_open_state_only = sorted(
        set(
            ActionItemPushState.objects.filter(closed_at__isnull=True)
            .exclude(user_id__in=with_subscription)
            .values_list("user_id", flat=True)
            .distinct()
        )
    )
    user_ids = with_subscription + with_open_state_only
    return user_ids[:limit], len(user_ids)


def requested_user_ids(*, limit: int) -> tuple[list[int], int]:
    """Users whose active subscriptions were marked by hooks, oldest request first; (first `limit`, total)."""
    rows = (
        PushSubscription.objects.filter(revoked_at__isnull=True, sync_requested_at__isnull=False)
        .values("user_id")
        .annotate(first_requested=Min("sync_requested_at"))
        .order_by("first_requested", "user_id")
    )
    user_ids = [row["user_id"] for row in rows]
    return user_ids[:limit], len(user_ids)


class Command(BaseCommand):
    help = "Send Web Push notifications of action items (hook-requested users or full catch-up)."

    def add_arguments(self, parser):
        parser.add_argument("--max-users", type=int, default=500, help="Users per run (default 500).")
        parser.add_argument(
            "--max-seconds",
            type=float,
            default=0,
            help="Stop starting new users after this many seconds (default 0: no limit).",
        )
        parser.add_argument(
            "--requested-only",
            action="store_true",
            help="Only users marked by approval hooks since their last sync.",
        )

    def handle(self, *args, **options):
        if not push_services.web_push_enabled():
            self.stdout.write("Web Push is off (VAPID keys are not set): nothing to do.")
            return
        started = monotonic()
        max_users = max(int(options["max_users"]), 0)
        max_seconds = max(float(options["max_seconds"]), 0)
        mode = "requested" if options["requested_only"] else "full"
        select = requested_user_ids if options["requested_only"] else candidate_user_ids
        user_ids, total = select(limit=max_users)
        if total > len(user_ids):
            logger.warning(
                "sync_action_item_push mode=%s: %s of %s users left for the next run by --max-users",
                mode,
                total - len(user_ids),
                total,
            )

        users = get_user_model().objects.in_bulk(user_ids)
        processed = sent = errors = 0
        for user_id in user_ids:
            if max_seconds and monotonic() - started >= max_seconds:
                logger.warning(
                    "sync_action_item_push mode=%s: %s users left for the next run by --max-seconds",
                    mode,
                    len(user_ids) - processed,
                )
                break
            processed += 1
            user = users.get(user_id)
            if user is None:
                continue
            try:
                sent += push_services.sync_user_action_item_push(user=user)
            except Exception:
                errors += 1
                logger.exception("sync_action_item_push failed user_id=%s", user.id)
        duration = monotonic() - started
        logger.info(
            "sync_action_item_push done mode=%s users=%s sent=%s errors=%s duration=%.2fs",
            mode,
            processed,
            sent,
            errors,
            duration,
        )
        self.stdout.write(f"mode={mode} users={processed} sent={sent} errors={errors} duration={duration:.2f}s")
