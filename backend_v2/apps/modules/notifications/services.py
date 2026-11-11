"""Aggregated "action required" items for the portal notifications screen."""
from __future__ import annotations

import logging
from collections.abc import Callable

from apps.modules.investments.registry import MODULE_KEY as INVESTMENTS_MODULE_KEY
from apps.modules.investments.services import (
    list_invest_return_action_items,
    list_project_investment_action_items,
)
from apps.modules.requests.services import list_request_action_items
from apps.tenants.permissions import has_effective_module_access

logger = logging.getLogger(__name__)

ActionItemsProvider = Callable[..., list[dict]]


def _providers_for_user(*, tenant, user) -> list[ActionItemsProvider]:
    providers: list[ActionItemsProvider] = [list_request_action_items]
    # Investment items link to /investments, which is guarded by HasEffectiveModuleAccess
    # (module switch + role). Without that access the link would end in 403, so such
    # approvers keep getting these items only through Telegram.
    if has_effective_module_access(user=user, tenant=tenant, module_key=INVESTMENTS_MODULE_KEY):
        providers.extend([list_invest_return_action_items, list_project_investment_action_items])
    return providers


def collect_action_items(*, tenant, user) -> list[dict]:
    """All objects whose current approval step waits on `user`, newest first.

    A failing provider is logged and skipped so one module cannot break the screen.
    """
    items: list[dict] = []
    for provider in _providers_for_user(tenant=tenant, user=user):
        try:
            items.extend(provider(tenant=tenant, user=user))
        except Exception:
            logger.exception(
                "action_items provider failed provider=%s tenant_id=%s user_id=%s",
                getattr(provider, "__name__", repr(provider)),
                tenant.id,
                user.id,
            )
    items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return items
