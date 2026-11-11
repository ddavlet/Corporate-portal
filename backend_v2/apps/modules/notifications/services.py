"""Aggregated "action required" items for the portal notifications screen."""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from urllib.parse import quote

from apps.modules.investments.registry import MODULE_KEY as INVESTMENTS_MODULE_KEY
from apps.modules.investments.services import (
    list_invest_return_action_items,
    list_project_investment_action_items,
)
from apps.modules.requests.services import list_request_action_items
from apps.tenants.models import Tenant
from apps.tenants.shared_host import member_tenants
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


def _collect_action_items_reporting_failure(*, tenant, user) -> tuple[list[dict], bool]:
    """`collect_action_items` plus whether any provider failed (its items are then missing)."""
    items: list[dict] = []
    failed = False
    for provider in _providers_for_user(tenant=tenant, user=user):
        try:
            items.extend(provider(tenant=tenant, user=user))
        except Exception:
            failed = True
            logger.exception(
                "action_items provider failed provider=%s tenant_id=%s user_id=%s",
                getattr(provider, "__name__", repr(provider)),
                tenant.id,
                user.id,
            )
    items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return items, failed


def collect_action_items(*, tenant, user) -> list[dict]:
    """All objects whose current approval step waits on `user`, newest first.

    A failing provider is logged and skipped so one module cannot break the screen.
    """
    items, _failed = _collect_action_items_reporting_failure(tenant=tenant, user=user)
    return items


def active_member_tenants(*, user) -> list[Tenant]:
    """Active tenants where `user` has an active membership, by name."""
    return list(member_tenants(user=user))


def with_company_param(link: str, subdomain: str) -> str:
    """Append `company=<subdomain>` so the shared portal opens the link in that company."""
    separator = "&" if "?" in link else "?"
    return f"{link}{separator}company={quote(subdomain, safe='')}"


def collect_action_items_by_tenant(*, user, tenants: Iterable[Tenant] | None = None) -> list[tuple[Tenant, list[dict]]]:
    """`collect_action_items` for every company of `user` (or the given `tenants`).

    A company that fails as a whole is logged and returned with no items, so one company
    cannot break the screen or the company switcher.
    """
    result: list[tuple[Tenant, list[dict]]] = []
    for tenant in active_member_tenants(user=user) if tenants is None else tenants:
        try:
            items = collect_action_items(tenant=tenant, user=user)
        except Exception:
            logger.exception("action_items tenant failed tenant_id=%s user_id=%s", tenant.id, user.id)
            items = []
        result.append((tenant, items))
    return result


def collect_all_action_items(*, user) -> list[dict]:
    """Action items of all companies of `user`, newest first, each with `tenant` and a `company=` link."""
    items: list[dict] = []
    for tenant, tenant_items in collect_action_items_by_tenant(user=user):
        company = {"subdomain": tenant.subdomain, "name": tenant.name}
        for item in tenant_items:
            items.append({**item, "tenant": company, "link": with_company_param(item["link"], tenant.subdomain)})
    items.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return items


def collect_action_items_by_tenant_reporting_failures(
    *, user
) -> tuple[list[tuple[Tenant, list[dict]]], set[str]]:
    """`collect_action_items_by_tenant` plus subdomains whose items may be incomplete.

    For Web Push: an item missing because its provider failed must not count as closed
    (it would be pushed again on the next successful sync), so the caller keeps the
    open push state of those companies as is.
    """
    result: list[tuple[Tenant, list[dict]]] = []
    failed_subdomains: set[str] = set()
    for tenant in active_member_tenants(user=user):
        try:
            items, failed = _collect_action_items_reporting_failure(tenant=tenant, user=user)
        except Exception:
            logger.exception("action_items tenant failed tenant_id=%s user_id=%s", tenant.id, user.id)
            items, failed = [], True
        if failed:
            failed_subdomains.add(tenant.subdomain)
        result.append((tenant, items))
    return result, failed_subdomains
