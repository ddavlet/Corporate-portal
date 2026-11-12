"""Hooks that keep Web Push of action items in sync with approval changes.

Everything runs after commit (`transaction.on_commit`), so nothing is marked for a
rolled-back decision. The hooks only mark the affected users' subscriptions (one cheap
UPDATE); the `sync_action_item_push --requested-only` cron run sends, so a slow push service
never delays the portal response or the Telegram webhook. With Web Push off (no VAPID keys)
the hooks return before touching the database.
"""

from __future__ import annotations

import functools
import logging

from django.db import transaction
from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from apps.modules.notifications import push_services
from apps.modules.requests.approval_events import KIND_REQUEST
from apps.modules.requests.models import Request
from apps.tenants.models import Tenant

logger = logging.getLogger(__name__)

_DELETE_USER_IDS_ATTR = "_action_item_push_user_ids"


def on_approvals_changed(*, tenant_id: int, kind: str, object_id: int) -> None:
    """Handler of the requests/investments `approvals_changed` events (already after commit)."""
    if not push_services.web_push_enabled():
        return
    tenant = Tenant.objects.filter(pk=tenant_id).first()
    if tenant is None:
        return
    push_services.request_sync_for_object(tenant=tenant, kind=kind, object_id=object_id)


def _sync_request_after_commit(request_obj: Request) -> None:
    if not push_services.web_push_enabled():
        return
    transaction.on_commit(
        functools.partial(
            on_approvals_changed, tenant_id=request_obj.tenant_id, kind=KIND_REQUEST, object_id=request_obj.pk
        ),
        robust=True,
    )


def on_request_payed(*, request_obj: Request) -> None:
    _sync_request_after_commit(request_obj)


def on_request_rejected(*, request_obj: Request) -> None:
    # Runs inside the rejected handlers' savepoint: only schedules, sends after the outer commit.
    _sync_request_after_commit(request_obj)


@receiver(pre_delete, sender=Request, dispatch_uid="notifications_push_collect_on_request_delete")
def collect_users_before_request_delete(sender, instance: Request, **kwargs) -> None:
    if not push_services.web_push_enabled():
        return
    try:
        setattr(
            instance,
            _DELETE_USER_IDS_ATTR,
            push_services.affected_user_ids(tenant=instance.tenant, kind=KIND_REQUEST, object_id=instance.pk),
        )
    except Exception:
        logger.exception("web_push pre_delete collect failed request_id=%s", instance.pk)


@receiver(post_delete, sender=Request, dispatch_uid="notifications_push_sync_on_request_delete")
def sync_users_after_request_delete(sender, instance: Request, **kwargs) -> None:
    user_ids = getattr(instance, _DELETE_USER_IDS_ATTR, None)
    if not user_ids:
        return
    transaction.on_commit(functools.partial(push_services.request_sync_for_users, user_ids), robust=True)
