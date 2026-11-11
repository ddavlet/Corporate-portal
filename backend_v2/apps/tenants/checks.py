"""Startup checks for the shared portal host (PORTAL_SHARED_HOST)."""

from __future__ import annotations

import logging

from django.core.checks import Tags, Warning, register
from django.db import DatabaseError

logger = logging.getLogger(__name__)


@register(Tags.database)
def check_reserved_subdomains_unused(app_configs=None, **kwargs):
    """Warn when an active tenant uses a slug reserved for the shared host (`app`, its first label).

    Such a tenant is never resolved by Host on the shared host, so its subdomain address stops
    working once the shared host is configured. Runs only with database checks (migrate, test).
    """
    from apps.tenants.shared_host import reserved_tenants_in_use

    try:
        taken = reserved_tenants_in_use()
    except DatabaseError:
        # Tables may not exist yet (first migrate); nothing to check then.
        logger.warning("reserved subdomain check skipped: tenants table is not available")
        return []
    if not taken:
        return []
    return [
        Warning(
            f"Active tenant uses a subdomain reserved for the shared portal host: {', '.join(taken)}.",
            hint="Choose another PORTAL_SHARED_HOST or rename the tenant; it is not reachable on the shared host.",
            id="tenants.W001",
        )
    ]
