from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send daily task digest via Telegram to every active tenant user who has a chat_id."

    def handle(self, *args, **options) -> None:
        from apps.modules.tasks.models import TasksConfig
        from apps.modules.tasks.notifications.digest_formatter import digest_buttons, format_digest
        from apps.modules.tasks.services import task_service
        from apps.modules.telegram_approvals.services import (
            get_tenant_bot_token,
            post_messaging_gateway,
        )
        from apps.tenants.models import TenantMembership

        memberships = (
            TenantMembership.objects.filter(is_active=True)
            .select_related("user", "tenant")
            .order_by("tenant_id", "user_id")
        )

        sent = skipped_no_tg = skipped_no_token = skipped_empty = 0
        # Cache per-tenant data that is constant across all users in the same tenant.
        _webapp_url_cache: dict[int, str] = {}
        _bot_token_cache: dict[int, str | None] = {}

        for membership in memberships.iterator():
            user = membership.user
            tenant = membership.tenant

            if not user.telegram_from_id:
                skipped_no_tg += 1
                continue

            if tenant.pk not in _bot_token_cache:
                _bot_token_cache[tenant.pk] = get_tenant_bot_token(tenant)
            bot_token = _bot_token_cache[tenant.pk]
            if not bot_token:
                skipped_no_token += 1
                continue

            try:
                dashboard = task_service.get_user_dashboard(user=user, tenant=tenant)
            except Exception:
                logger.exception(
                    "send_task_digest: failed to build dashboard user=%s tenant=%s",
                    user.pk,
                    tenant.pk,
                )
                continue

            if not (dashboard["new"] or dashboard["in_progress"] or dashboard["done_recent"]):
                skipped_empty += 1
                continue

            message_text = format_digest(user=user, dashboard=dashboard)

            if tenant.pk not in _webapp_url_cache:
                try:
                    cfg = TasksConfig.objects.filter(tenant=tenant).first()
                    _webapp_url_cache[tenant.pk] = (cfg.tasks_webapp_url if cfg else "") or ""
                except Exception:
                    _webapp_url_cache[tenant.pk] = ""
            webapp_url = _webapp_url_cache[tenant.pk]

            payload = {
                "action": "send",
                "text": message_text,
                "recipient_id": str(user.telegram_from_id),
                "bot_token": bot_token,
                "tenant_id": str(tenant.pk),
                "buttons": digest_buttons(tasks_webapp_url=webapp_url),
            }

            try:
                post_messaging_gateway(tenant=tenant, payload=payload)
                sent += 1
            except Exception:
                logger.exception(
                    "send_task_digest: failed to send user=%s tenant=%s",
                    user.pk,
                    tenant.pk,
                )

        self.stdout.write(
            f"send_task_digest: sent={sent} "
            f"skipped_no_tg={skipped_no_tg} "
            f"skipped_no_token={skipped_no_token} "
            f"skipped_empty={skipped_empty}"
        )
