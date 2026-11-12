"""Web Push of "action required" items: one show-push per new item, closing by `active_tags`.

There is no close-push (iOS forbids silent push): an item that stops waiting on the user only
gets `closed_at`; the service worker drops its notification on the next push (`active_tags`)
or when the app is opened.

Nothing is sent in the thread of an HTTP request: approval hooks only mark the affected users
(`request_sync_for_object`), and the `sync_action_item_push` cron command sends, outside DB
transactions, with a short timeout, only to allow-listed push services, without redirects,
and never raises.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from decimal import Decimal
from urllib.parse import urlsplit

import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from pywebpush import WebPushException, webpush

from apps.modules.investments.approval_events import KIND_INVEST_RETURN, KIND_PROJECT_INVESTMENT
from apps.modules.investments.models import InvestmentReturnApproval, ProjectInvestmentApproval
from apps.modules.notifications.models import ActionItemPushState, PushSubscription
from apps.modules.notifications.services import (
    collect_action_items_by_tenant_reporting_failures,
    with_company_param,
)
from apps.modules.requests.approval_events import KIND_REQUEST
from apps.modules.requests.models import Approval

logger = logging.getLogger(__name__)

PUSH_TIMEOUT_SECONDS = 3
PUSH_TTL_SECONDS = 86400
# Push services accept about 4 KB of payload; past this size `active_tags` is sent as null
# (the service worker then keeps the shown notifications instead of closing the wrong ones).
MAX_PAYLOAD_BYTES = 3000
APP_URL_PREFIX = "/app"
# Devices per user; subscribing one more revokes the least recently subscribed.
MAX_ACTIVE_SUBSCRIPTIONS_PER_USER = 10
# Push services of the browsers we support (Chrome/Android/Samsung/Opera, Safari/iOS,
# Firefox, Edge). Any other endpoint host is refused: the server POSTs to the endpoint.
PUSH_SERVICE_HOSTS = frozenset({"fcm.googleapis.com"})
PUSH_SERVICE_HOST_SUFFIXES = (".push.apple.com", ".push.services.mozilla.com", ".notify.windows.com")


class PushEndpointTaken(Exception):
    """The endpoint is an active subscription of another user and the keys do not match."""


def web_push_enabled() -> bool:
    return bool(
        getattr(settings, "VAPID_PUBLIC_KEY", "")
        and getattr(settings, "VAPID_PRIVATE_KEY", "")
        and getattr(settings, "VAPID_SUBJECT", "")
    )


def endpoint_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode("utf-8")).hexdigest()


def endpoint_allowed(endpoint: str) -> bool:
    """https on port 443 of a known push service; no userinfo, no IP literals or other hosts."""
    if not endpoint or any(ch in endpoint for ch in "\\ \t\r\n"):
        return False
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or port not in (None, 443):
        return False
    if parts.username is not None or parts.password is not None:
        return False
    host = parts.hostname or ""
    return host in PUSH_SERVICE_HOSTS or any(
        host.endswith(suffix) and len(host) > len(suffix) for suffix in PUSH_SERVICE_HOST_SUFFIXES
    )


class _NoRedirectSession(requests.Session):
    """A redirect from a push service is never followed (it could point inside our network)."""

    def request(self, *args, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(*args, **kwargs)


def push_tag(*, subdomain: str, kind: str, object_id: int) -> str:
    """Notification tag, unique across companies: `<subdomain>:<kind>-<id>`."""
    return f"{subdomain}:{kind}-{object_id}"


def _format_amount(amount) -> str:
    if amount is None:
        return ""
    value = Decimal(amount).quantize(Decimal("0.01"))
    text = f"{value:,.2f}".replace(",", " ")
    return text[:-3] if text.endswith(".00") else text


def build_show_payload(*, tenant, item: dict, tag: str, count: int, active_tags: list[str]) -> dict:
    body = " ".join(part for part in (_format_amount(item.get("amount")), item.get("currency") or "") if part)
    payload = {
        "type": "show",
        "tag": tag,
        "title": f"{tenant.name}: {item.get('title') or ''}".strip(),
        "body": body,
        "url": APP_URL_PREFIX + with_company_param(item["link"], tenant.subdomain),
        "count": count,
        "active_tags": active_tags,
    }
    if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        payload["active_tags"] = None
    return payload


def send_web_push(subscription: PushSubscription, payload: dict) -> bool:
    """Send one push; True on success. 404/410 revoke the subscription; never raises.

    An endpoint outside the allow-list is revoked without a request. Logs carry only ids
    and the HTTP status: the endpoint (and an exception text that may contain it) and the
    subscription keys are never written.
    """
    if not endpoint_allowed(subscription.endpoint):
        _revoke_subscription(subscription, PushSubscription.REVOKE_REASON_NOT_ALLOWED)
        logger.warning(
            "web_push endpoint not allowed, subscription revoked subscription_id=%s user_id=%s",
            subscription.pk,
            subscription.user_id,
        )
        return False
    try:
        with _NoRedirectSession() as session:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
                },
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=PUSH_TTL_SECONDS,
                timeout=PUSH_TIMEOUT_SECONDS,
                requests_session=session,
            )
    except WebPushException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code in (404, 410):
            _revoke_subscription(subscription, PushSubscription.REVOKE_REASON_GONE)
            logger.info(
                "web_push subscription gone subscription_id=%s user_id=%s status=%s",
                subscription.pk,
                subscription.user_id,
                status_code,
            )
            return False
        logger.error(
            "web_push send failed subscription_id=%s user_id=%s status=%s error=%s",
            subscription.pk,
            subscription.user_id,
            status_code,
            type(exc).__name__,
        )
        return False
    except Exception as exc:
        logger.error(
            "web_push send failed subscription_id=%s user_id=%s error=%s",
            subscription.pk,
            subscription.user_id,
            type(exc).__name__,
        )
        return False
    now = timezone.now()
    PushSubscription.objects.filter(pk=subscription.pk).update(last_success_at=now)
    subscription.last_success_at = now
    return True


def _revoke_subscription(subscription: PushSubscription, reason: str) -> None:
    now = timezone.now()
    PushSubscription.objects.filter(pk=subscription.pk, revoked_at__isnull=True).update(
        revoked_at=now, revoke_reason=reason, updated_at=now
    )
    subscription.revoked_at = now
    subscription.revoke_reason = reason


def _step_key(item: dict) -> str:
    """The approval step an item is about: a new step of the same object is a new push."""
    return f"{item.get('step')}:{item.get('approval_id')}"


def _tag_subdomain(tag: str) -> str:
    return tag.split(":", 1)[0]


def _open_states(user) -> dict[str, str]:
    """Open push states of `user`: tag -> step_key."""
    return dict(
        ActionItemPushState.objects.filter(user=user, closed_at__isnull=True).values_list("tag", "step_key")
    )


def _current_items(user) -> tuple[dict[str, tuple], set[str]]:
    """Action items of `user` in all companies by tag, and subdomains whose items may be incomplete."""
    by_tenant, failed_subdomains = collect_action_items_by_tenant_reporting_failures(user=user)
    current: dict[str, tuple] = {}
    for tenant, items in by_tenant:
        for item in items:
            tag = push_tag(subdomain=tenant.subdomain, kind=item["kind"], object_id=item["id"])
            current[tag] = (tenant, item, _step_key(item))
    return current, failed_subdomains


def _claim_state(*, tenant, user, tag: str, step_key: str, open_step_key: str | None, now) -> bool:
    """Mark `tag` at `step_key` as notified for `user`; False when another sync already claimed it.

    `open_step_key` is the step of the open state of this tag (None when it is not open):
    the conditional updates make two concurrent syncs send one push, not two.
    """
    if open_step_key is not None:
        return bool(
            ActionItemPushState.objects.filter(
                user=user, tag=tag, closed_at__isnull=True, step_key=open_step_key
            ).update(tenant=tenant, step_key=step_key, sent_at=now)
        )
    reopened = ActionItemPushState.objects.filter(user=user, tag=tag, closed_at__isnull=False).update(
        tenant=tenant, step_key=step_key, sent_at=now, closed_at=None
    )
    if reopened:
        return True
    try:
        with transaction.atomic():
            ActionItemPushState.objects.create(tenant=tenant, user=user, tag=tag, step_key=step_key, sent_at=now)
    except IntegrityError:
        return False
    return True


def _release_state(*, user, tag: str, step_key: str, now) -> None:
    """Undo a claim whose push reached no device: the next sync sees the item as new again."""
    ActionItemPushState.objects.filter(user=user, tag=tag, step_key=step_key, closed_at__isnull=True).update(
        closed_at=now
    )


def _close_all_states(*, user, now) -> None:
    ActionItemPushState.objects.filter(user=user, closed_at__isnull=True).update(closed_at=now)


def _mark_synced(*, user, started, now) -> None:
    PushSubscription.objects.filter(user=user, revoked_at__isnull=True).update(synced_at=now)
    # A request made after this sync started stays and is handled by the next run.
    PushSubscription.objects.filter(user=user, sync_requested_at__lte=started).update(sync_requested_at=None)


def sync_user_action_item_push(*, user) -> int:
    """Bring push state of `user` in line with their action items in all companies.

    New items (or a new step of an item) get a state row and one show-push per active
    subscription; items that are gone only get `closed_at`. A repeated call without changes
    sends nothing. Items of a company whose collection failed are neither closed nor dropped
    from `active_tags`. A push that reached no device for a transient reason (not 404/410)
    is released and retried by the next sync. Returns pushes sent.
    """
    if not web_push_enabled():
        return 0
    started = timezone.now()
    if not user.is_active:
        for subscription in PushSubscription.objects.filter(user=user, revoked_at__isnull=True):
            _revoke_subscription(subscription, PushSubscription.REVOKE_REASON_INACTIVE)
        _close_all_states(user=user, now=started)
        return 0
    subscriptions = list(PushSubscription.objects.filter(user=user, revoked_at__isnull=True).order_by("id"))
    open_states = _open_states(user)
    if not subscriptions:
        # No device to show or drop notifications on; subscribing again records a baseline.
        if open_states:
            _close_all_states(user=user, now=started)
        return 0

    current, failed_subdomains = _current_items(user)
    now = timezone.now()
    kept_tags = {tag for tag in open_states if tag not in current and _tag_subdomain(tag) in failed_subdomains}
    gone_tags = open_states.keys() - current.keys() - kept_tags
    if gone_tags:
        ActionItemPushState.objects.filter(user=user, tag__in=gone_tags, closed_at__isnull=True).update(closed_at=now)

    new_tags = [tag for tag, (_tenant, _item, key) in current.items() if open_states.get(tag) != key]
    active_tags = sorted(set(current) | kept_tags)
    sent = 0
    # Oldest first, so the newest notification ends up on top.
    for tag in sorted(new_tags, key=lambda t: (current[t][1]["created_at"], current[t][1]["id"])):
        tenant, item, key = current[tag]
        if not _claim_state(tenant=tenant, user=user, tag=tag, step_key=key, open_step_key=open_states.get(tag), now=now):
            continue
        payload = build_show_payload(tenant=tenant, item=item, tag=tag, count=len(active_tags), active_tags=active_tags)
        delivered = transient_failures = 0
        for subscription in subscriptions:
            if subscription.revoked_at is not None:
                continue
            if send_web_push(subscription, payload):
                delivered += 1
            elif subscription.revoked_at is None:
                transient_failures += 1
        sent += delivered
        if not delivered and transient_failures:
            _release_state(user=user, tag=tag, step_key=key, now=now)
            logger.warning("web_push not delivered, retry on next sync user_id=%s tag=%s", user.id, tag)
    _mark_synced(user=user, started=started, now=timezone.now())
    return sent


def record_action_item_baseline(*, user) -> int:
    """Mark the current items of `user` as already notified, without sending (first device).

    Turning notifications on must not bring one push per item that was already waiting;
    only items that appear afterwards are pushed. Returns the number of items recorded.
    """
    if not web_push_enabled():
        return 0
    current, _failed = _current_items(user)
    open_states = _open_states(user)
    now = timezone.now()
    recorded = 0
    for tag, (tenant, _item, key) in current.items():
        if open_states.get(tag) == key:
            continue
        if _claim_state(tenant=tenant, user=user, tag=tag, step_key=key, open_step_key=open_states.get(tag), now=now):
            recorded += 1
    return recorded


def save_subscription(*, user, endpoint: str, p256dh: str, auth: str, user_agent: str) -> bool:
    """Upsert the device subscription of `user` by endpoint hash; True when created.

    An active subscription of another user is taken over only with the same keys (the same
    browser subscription after a change of user on the device); otherwise `PushEndpointTaken`.
    Past `MAX_ACTIVE_SUBSCRIPTIONS_PER_USER` the least recently subscribed devices are revoked.
    The first device of the user records a baseline of the items already waiting.
    """
    digest = endpoint_hash(endpoint)
    existing = PushSubscription.objects.filter(endpoint_hash=digest).first()
    if (
        existing is not None
        and existing.user_id != user.id
        and existing.revoked_at is None
        and (existing.p256dh, existing.auth) != (p256dh, auth)
    ):
        raise PushEndpointTaken()
    had_active = PushSubscription.objects.filter(user=user, revoked_at__isnull=True).exclude(endpoint_hash=digest).exists()
    fields = {
        "user": user,
        "endpoint": endpoint,
        "p256dh": p256dh,
        "auth": auth,
        "user_agent": user_agent[:500],
        "revoked_at": None,
        "revoke_reason": "",
    }
    try:
        with transaction.atomic():
            _, created = PushSubscription.objects.update_or_create(endpoint_hash=digest, defaults=fields)
    except IntegrityError:
        # A concurrent subscribe created the row first: update it under the same takeover rule.
        updated = (
            PushSubscription.objects.filter(endpoint_hash=digest)
            .filter(Q(user=user) | Q(revoked_at__isnull=False) | Q(p256dh=p256dh, auth=auth))
            .update(**fields, updated_at=timezone.now())
        )
        if not updated:
            raise PushEndpointTaken() from None
        created = False
    _revoke_over_limit(user=user)
    if not had_active:
        try:
            record_action_item_baseline(user=user)
        except Exception:
            logger.exception("web_push baseline failed user_id=%s", user.id)
    return created


def _revoke_over_limit(*, user) -> None:
    extra_ids = list(
        PushSubscription.objects.filter(user=user, revoked_at__isnull=True)
        .order_by("-updated_at", "-id")
        .values_list("id", flat=True)[MAX_ACTIVE_SUBSCRIPTIONS_PER_USER:]
    )
    if extra_ids:
        now = timezone.now()
        PushSubscription.objects.filter(id__in=extra_ids, revoked_at__isnull=True).update(
            revoked_at=now, revoke_reason=PushSubscription.REVOKE_REASON_LIMIT, updated_at=now
        )


def _pending_approver_ids(*, tenant, kind: str, object_id: int) -> set[int]:
    if kind == KIND_REQUEST:
        qs = Approval.objects.filter(
            request_id=object_id, request__tenant=tenant, decision=Approval.DECISION_PENDING
        )
    elif kind == KIND_INVEST_RETURN:
        qs = InvestmentReturnApproval.objects.filter(
            tenant=tenant, invest_return_id=object_id, decision=InvestmentReturnApproval.DECISION_PENDING
        )
    elif kind == KIND_PROJECT_INVESTMENT:
        qs = ProjectInvestmentApproval.objects.filter(
            tenant=tenant, project_investment_id=object_id, decision=ProjectInvestmentApproval.DECISION_PENDING
        )
    else:
        return set()
    return set(qs.filter(approver_user__isnull=False).values_list("approver_user_id", flat=True))


def affected_user_ids(*, tenant, kind: str, object_id: int) -> set[int]:
    """Pending approvers of the object plus users with an open push state for its tag."""
    tag = push_tag(subdomain=tenant.subdomain, kind=kind, object_id=object_id)
    open_state_users = ActionItemPushState.objects.filter(tag=tag, closed_at__isnull=True).values_list(
        "user_id", flat=True
    )
    return _pending_approver_ids(tenant=tenant, kind=kind, object_id=object_id) | set(open_state_users)


def sync_users(user_ids: Iterable[int]) -> int:
    """`sync_user_action_item_push` for each user, in this thread (sends); one failing user does not stop the others.

    Not for HTTP requests or hooks: they use `request_sync_for_users` and leave sending to cron.
    """
    sent = 0
    for user in get_user_model().objects.filter(id__in=set(user_ids)).order_by("id"):
        try:
            sent += sync_user_action_item_push(user=user)
        except Exception:
            logger.exception("web_push sync failed user_id=%s", user.id)
    return sent


def request_sync_for_users(user_ids: Iterable[int]) -> int:
    """Mark active subscriptions of the users for the next cron sync; nothing is sent here."""
    user_ids = set(user_ids)
    if not user_ids or not web_push_enabled():
        return 0
    return PushSubscription.objects.filter(user_id__in=user_ids, revoked_at__isnull=True).update(
        sync_requested_at=timezone.now()
    )


def request_sync_for_object(*, tenant, kind: str, object_id: int) -> int:
    """`request_sync_for_users` for everyone the object's step change may concern (cheap, no network)."""
    if not web_push_enabled():
        return 0
    return request_sync_for_users(affected_user_ids(tenant=tenant, kind=kind, object_id=object_id))


def sync_users_for_object(*, tenant, kind: str, object_id: int) -> int:
    """Sync (and send to) everyone the object's step change may concern, in this thread; see `sync_users`."""
    if not web_push_enabled():
        return 0
    return sync_users(affected_user_ids(tenant=tenant, kind=kind, object_id=object_id))
