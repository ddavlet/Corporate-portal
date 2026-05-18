"""
Kolberg MCP Server

Entry point for the Model Context Protocol server.
Run via the Django management command:

    python manage.py run_mcp_server

Or directly (sets up Django itself):

    python -m apps.mcp_server.server

The server communicates over stdio (standard MCP transport) so AI tools
can spawn it as a subprocess.
"""

from __future__ import annotations

import os


def _bootstrap_django() -> None:
    """Set up Django if not already configured (for direct invocation)."""
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    import django
    django.setup()


# When this module is run directly (not via manage.py), bootstrap Django first.
if not os.environ.get("_DJANGO_SETUP_DONE"):
    _bootstrap_django()
    os.environ["_DJANGO_SETUP_DONE"] = "1"

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
    instructions=(
        "Provides read-only access to Kolberg tenant data. "
        "Every tool requires a JWT `token` (Bearer token from /api/auth/token/) "
        "and a `tenant_id`. Access is role-scoped: each tool checks that the "
        "calling user has the required role and that the module is enabled for the tenant."
    ),
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
    token: str,
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
        token: JWT access token.
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
            token=token, tenant_id=tenant_id, status=status,
            currency=currency, payment_type=payment_type, urgency=urgency,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def get_request(token: str, tenant_id: int, request_id: int) -> dict:
    """Get a single request by ID, including its approval steps.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        request_id: Request primary key.
    """
    try:
        return req_tools.get_request(token=token, tenant_id=tenant_id, request_id=request_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@mcp.tool()
def list_request_categories(token: str, tenant_id: int) -> list:
    """List active request categories for a tenant.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return req_tools.list_request_categories(token=token, tenant_id=tenant_id)
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Financial operations (финансовые операции)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_cash_expenses(
    token: str,
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    currency: str = "",
    limit: int = 50,
) -> list:
    """List cash expenses for a tenant.

    Required roles: admin, director, cashier.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        date_from: Filter expense_at >= this date (YYYY-MM-DD).
        date_to: Filter expense_at <= this date (YYYY-MM-DD).
        currency: Filter by currency. One of: UZS, USD, EUR, RUB.
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_cash_expenses(
            token=token, tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, currency=currency, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_cash_revenues(
    token: str,
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List cash revenues for a tenant.

    Required roles: admin, director, cashier.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        date_from: Filter revenue_at >= this date (YYYY-MM-DD).
        date_to: Filter revenue_at <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_cash_revenues(
            token=token, tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_bank_expenses(
    token: str,
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List bank expenses for a tenant.

    Required roles: admin, director, accountant.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        date_from: Filter doc_date >= this date (YYYY-MM-DD).
        date_to: Filter doc_date <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_bank_expenses(
            token=token, tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_bank_revenues(
    token: str,
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List bank revenues for a tenant.

    Required roles: admin, director, accountant.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        date_from: Filter doc_date >= this date (YYYY-MM-DD).
        date_to: Filter doc_date <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_bank_revenues(
            token=token, tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_card_expenses(
    token: str,
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """List corporate card expenses for a tenant.

    Required roles: admin, director, accountant, cashier.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        date_from: Filter expense_at >= this date (YYYY-MM-DD).
        date_to: Filter expense_at <= this date (YYYY-MM-DD).
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_card_expenses(
            token=token, tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_payroll_documents(token: str, tenant_id: int, limit: int = 50) -> list:
    """List payroll documents for a tenant.

    Required roles: admin, director, accountant.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        limit: Max number of results (1–200, default 50).
    """
    try:
        return fin_tools.list_payroll_documents(token=token, tenant_id=tenant_id, limit=limit)
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def get_payroll_document(token: str, tenant_id: int, document_id: int) -> dict:
    """Get a payroll document and all its lines by ID.

    Required roles: admin, director, accountant.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        document_id: PayrollDocument primary key.
    """
    try:
        return fin_tools.get_payroll_document(
            token=token, tenant_id=tenant_id, document_id=document_id,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Reference directories (справочники)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_vendors(
    token: str,
    tenant_id: int,
    kind: str = "",
    name_search: str = "",
    limit: int = 100,
) -> list:
    """List vendors from the tenant directory.

    Required roles: admin, director, approver, requester, cashier, accountant.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
        kind: Filter by kind. One of: cash, transfer.
        name_search: Case-insensitive substring match on vendor name.
        limit: Max number of results (1–500, default 100).
    """
    try:
        return dir_tools.list_vendors(
            token=token, tenant_id=tenant_id,
            kind=kind, name_search=name_search, limit=limit,
        )
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_wallets(token: str, tenant_id: int) -> list:
    """List all wallets for a tenant (cash, bank, corporate card).

    Required roles: admin, director, accountant, cashier.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return dir_tools.list_wallets(token=token, tenant_id=tenant_id)
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------

@mcp.tool()
def get_integration_config(token: str, tenant_id: int) -> dict:
    """Get integration configuration for a tenant (admin only).

    Returns metadata about configured integrations. Encrypted secrets are
    never exposed — only whether each secret is set.

    Required roles: admin.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return int_tools.get_integration_config(token=token, tenant_id=tenant_id)
    except PermissionError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Tenant configuration
# ---------------------------------------------------------------------------

@mcp.tool()
def get_tenant_info(token: str, tenant_id: int) -> dict:
    """Get public metadata for a tenant.

    Required roles: admin, director.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.get_tenant_info(token=token, tenant_id=tenant_id)
    except PermissionError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@mcp.tool()
def list_module_configs(token: str, tenant_id: int) -> list:
    """List all module enable/disable flags for a tenant.

    Required roles: admin, director.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_module_configs(token=token, tenant_id=tenant_id)
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_user_roles(token: str, tenant_id: int) -> list:
    """List all user-role assignments for a tenant (admin only).

    Required roles: admin.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_user_roles(token=token, tenant_id=tenant_id)
    except PermissionError as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@mcp.tool()
def list_memberships(token: str, tenant_id: int) -> list:
    """List all tenant memberships (admin only).

    Required roles: admin.

    Args:
        token: JWT access token.
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_memberships(token=token, tenant_id=tenant_id)
    except PermissionError as e:
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
