"""
Kolberg MCP Server

Entry point for the Model Context Protocol server.
Run via the Django management command:

    KOLBERG_JWT_TOKEN=<access_token> python manage.py run_mcp_server

Or directly (sets up Django itself):

    KOLBERG_JWT_TOKEN=<access_token> python -m apps.mcp_server.server

The JWT token is read once from the KOLBERG_JWT_TOKEN environment variable
and is never passed as a tool-call parameter, keeping it out of MCP logs
and AI conversation history.

The server communicates over stdio (standard MCP transport).
"""

from __future__ import annotations

import os


def _bootstrap_django() -> None:
    """Set up Django if not already initialised (for direct invocation)."""
    from django.apps import apps
    if apps.ready:
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()


_bootstrap_django()

from mcp.server.fastmcp import FastMCP

from apps.mcp_server.tools import (
    requests as req_tools,
    finance as fin_tools,
    directories as dir_tools,
    integrations as int_tools,
    tenant_config as cfg_tools,
)

mcp = FastMCP(
    name="Kolberg Data Server",
    instructions="""
Kolberg is a multi-tenant financial management platform. This server provides
read-only access to one tenant's data. Authentication is handled automatically
via the KOLBERG_JWT_TOKEN environment variable set at server startup.

HOW TO START
1. Ask the user for their tenant_id (the numeric ID of their organization).
2. Call list_module_configs(tenant_id) to discover which modules are enabled
   for this tenant. Only call tools for modules that are enabled — disabled
   modules always return a permission error.
3. If access is denied, check the user's roles with list_user_roles(tenant_id)
   (requires admin role).

DATA DOMAINS AND TOOLS
- Requests (заявки):
    list_requests          — list with filters (status, currency, payment_type, urgency, date range)
    get_request            — single request with full approval chain
    list_request_categories — active categories for this tenant

- Cash (module key: "cash"):
    list_cash_expenses     — expenses with date/currency filters
    list_cash_revenues     — revenues with date filter (includes total_sum amount)

- Bank (module key: "bank"):
    list_bank_expenses     — bank debit operations with date filter
    list_bank_revenues     — bank credit operations with date filter

- Corporate card (module key: "corporate_card"):
    list_card_expenses     — card expenses with date filter

- Payroll (module key: "payroll"):
    list_payroll_documents — list documents
    get_payroll_document   — document with all employee lines

- Directories / справочники (module keys: "vendors", "wallets"):
    list_vendors           — vendor directory, filter by kind (cash/transfer) or name
    list_wallets           — all wallets (cash registers, bank accounts, card accounts)

- Integrations (admin only):
    get_integration_config — shows which integrations are configured (secrets never exposed)

- Tenant configuration (admin/director only):
    get_tenant_info        — tenant name, subdomain, feature flags
    list_module_configs    — which modules are enabled/disabled
    list_user_roles        — all user→role assignments (admin only)
    list_memberships       — all active members (admin only)

ROLE PERMISSIONS (who can access what)
- admin / director : all modules
- approver         : requests, vendors, notes
- requester        : requests, vendors, notes
- cashier          : requests, cash, corporate_card, wallets, vendors
- accountant       : requests, bank, payroll, corporate_card, wallets, vendors
- investor         : investments (no tools exposed yet)

ERRORS
All tools return {"error": "message"} (for dict tools) or [{"error": "message"}]
(for list tools) on failure. Always check for the "error" key before using results.
Common errors: invalid/expired token, wrong tenant_id, insufficient role, module disabled.

FILTERING
- Date filters accept YYYY-MM-DD format only. Invalid formats return a clear error.
- limit parameter: default 50, max 200 (max 500 for list_vendors).
- All results are scoped to the given tenant — cross-tenant access is impossible.
""",
)


def _err(msg: str) -> dict:
    return {"error": msg}


def _list_err(msg: str) -> list:
    return [{"error": msg}]


# ---------------------------------------------------------------------------
# Requests (заявки)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_requests(
    tenant_id: int,
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List requests (заявки) for a tenant with optional filters.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        tenant_id: Tenant primary key.
        status: Filter by status. One of: DRAFT, 1, 2, 3, 4, 5, APPROVED, PAYED, REJECTED.
        currency: Filter by currency. One of: UZS, USD, EUR, RUB.
        payment_type: Filter by payment type. One of: Наличные, Перечисление, Пополнение, Платежная карта.
        urgency: Filter by urgency. One of: Низко, Обычно, Срочно.
        date_from: Filter created_at >= this date (YYYY-MM-DD).
        date_to: Filter created_at <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return req_tools.list_requests(
            tenant_id=tenant_id, status=status,
            currency=currency, payment_type=payment_type, urgency=urgency,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def get_request(tenant_id: int, request_id: int) -> dict:
    """Get a single request by ID, including its approval steps.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        tenant_id: Tenant primary key.
        request_id: Request primary key.
    """
    try:
        return req_tools.get_request(tenant_id=tenant_id, request_id=request_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@mcp.tool()
def list_request_categories(tenant_id: int) -> list:
    """List active request categories for a tenant.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return req_tools.list_request_categories(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Financial operations (финансовые операции)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_cash_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    currency: str = "",
    limit: int = 50,
) -> list:
    """List cash expenses for a tenant.

    Required roles: admin, director, cashier.

    Args:
        tenant_id: Tenant primary key.
        date_from: Filter expense_at >= this date (YYYY-MM-DD).
        date_to: Filter expense_at <= this date (YYYY-MM-DD).
        currency: Filter by currency. One of: UZS, USD, EUR, RUB.
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_cash_expenses(
            tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, currency=currency, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_cash_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List cash revenues for a tenant.

    Required roles: admin, director, cashier.

    Args:
        tenant_id: Tenant primary key.
        date_from: Filter revenue_at >= this date (YYYY-MM-DD).
        date_to: Filter revenue_at <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_cash_revenues(
            tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_bank_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List bank expenses for a tenant.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key.
        date_from: Filter doc_date >= this date (YYYY-MM-DD).
        date_to: Filter doc_date <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_bank_expenses(
            tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_bank_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List bank revenues for a tenant.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key.
        date_from: Filter doc_date >= this date (YYYY-MM-DD).
        date_to: Filter doc_date <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_bank_revenues(
            tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_card_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List corporate card expenses for a tenant.

    Required roles: admin, director, accountant, cashier.

    Args:
        tenant_id: Tenant primary key.
        date_from: Filter expense_at >= this date (YYYY-MM-DD).
        date_to: Filter expense_at <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_card_expenses(
            tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_payroll_documents(tenant_id: int, limit: int = 50) -> list:
    """List payroll documents for a tenant.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key.
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_payroll_documents(tenant_id=tenant_id, limit=limit)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def get_payroll_document(tenant_id: int, document_id: int) -> dict:
    """Get a payroll document and all its lines by ID.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key.
        document_id: PayrollDocument primary key.
    """
    try:
        return fin_tools.get_payroll_document(tenant_id=tenant_id, document_id=document_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Reference directories (справочники)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_vendors(
    tenant_id: int,
    kind: str = "",
    name_search: str = "",
    limit: int = 100,
) -> list:
    """List vendors from the tenant directory.

    Required roles: admin, director, approver, requester, cashier, accountant.

    Args:
        tenant_id: Tenant primary key.
        kind: Filter by kind. One of: cash, transfer.
        name_search: Case-insensitive substring match on vendor name.
        limit: Max number of results (1–500, default 100).
    """
    try:
        return dir_tools.list_vendors(
            tenant_id=tenant_id, kind=kind, name_search=name_search, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_wallets(tenant_id: int) -> list:
    """List all wallets for a tenant (cash, bank, corporate card).

    Required roles: admin, director, accountant, cashier.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return dir_tools.list_wallets(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

@mcp.tool()
def get_integration_config(tenant_id: int) -> dict:
    """Get integration configuration for a tenant (admin only).

    Returns metadata about configured integrations. Encrypted secrets are
    never exposed — only whether each secret is set.

    Required roles: admin.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return int_tools.get_integration_config(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Tenant configuration
# ---------------------------------------------------------------------------

@mcp.tool()
def get_tenant_info(tenant_id: int) -> dict:
    """Get public metadata for a tenant.

    Required roles: admin, director.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.get_tenant_info(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@mcp.tool()
def list_module_configs(tenant_id: int) -> list:
    """List all module enable/disable flags for a tenant.

    Required roles: admin, director.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_module_configs(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_user_roles(tenant_id: int) -> list:
    """List all user-role assignments for a tenant (admin only).

    Required roles: admin.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_user_roles(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_memberships(tenant_id: int) -> list:
    """List all tenant memberships (admin only).

    Required roles: admin.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_memberships(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    run()
