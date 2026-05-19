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

from apps.mcp_server.django_tools import django_mcp_tool
from apps.mcp_server.tools import (
    requests as req_tools,
    finance as fin_tools,
    directories as dir_tools,
    integrations as int_tools,
    tenant_config as cfg_tools,
    investments as inv_tools,
    budgets as bud_tools,
)

mcp = FastMCP(
    name="Kolberg Data Server",
    instructions="""
Kolberg is a multi-tenant financial management platform. This server provides
read-only access to one tenant's data.

════════════════════════════════════════════════════════════
CRITICAL: SOURCE OF TRUTH FOR EXPENSES
════════════════════════════════════════════════════════════
ALL expenses in Kolberg are recorded as payment REQUESTS (заявки).
Cash and bank transaction records (list_cash_expenses, list_bank_expenses,
list_card_expenses) are raw accounting feeds used ONLY to reconcile whether
every expense has a matching request. They are NOT the source of truth.

DEFAULT BEHAVIOUR — always follow this:
  • When the user asks about expenses, spending, payments, or costs
    → use list_requests / get_request as the primary source.
  • Do NOT call list_cash_expenses / list_bank_expenses / list_card_expenses
    by default.

EXCEPTION — raw transaction data:
  • Only call cash/bank/card expense tools when the user EXPLICITLY asks for
    raw transaction data AND confirms they want to bypass requests.
  • Example trigger: "покажи мне сырые данные кассы" / "нужны транзакции банка
    напрямую, не через заявки".
  • When in doubt — ask the user before calling raw expense tools.

Revenues (list_cash_revenues, list_bank_revenues, list_card_revenues) are not
covered by requests and can be queried directly at any time.

════════════════════════════════════════════════════════════
HOW TO START A SESSION
════════════════════════════════════════════════════════════
1. list_my_tenants()            — discover which tenants the user belongs to.
2. get_my_role(tenant_id)       — understand the user's roles and permissions.
3. list_my_modules(tenant_id)   — see which modules are enabled and accessible.
4. Only then call domain-specific tools for enabled modules.

════════════════════════════════════════════════════════════
TOOLS BY DOMAIN
════════════════════════════════════════════════════════════
Requests / заявки (PRIMARY source for expenses):
  list_requests           — filter by status, currency, payment_type, urgency, date
  get_request             — full detail + approval chain for one request
  list_request_categories — categories configured for this tenant

Cash (module: "cash") — reconciliation only, see CRITICAL above:
  list_cash_expenses      — raw cash outflows
  list_cash_revenues      — cash inflows (safe to query directly)

Bank (module: "bank") — reconciliation only, see CRITICAL above:
  list_bank_expenses      — raw bank debits
  list_bank_revenues      — bank credits (safe to query directly)

Corporate card (module: "corporate_card") — reconciliation only:
  list_card_expenses      — raw card charges
  list_card_revenues      — card credits (safe to query directly)

Reports (module: "reports"):
  get_pnl_report          — full PnL: revenue + expenses split into operational /
                            other / invest_returns; expenses on billing_date with
                            amortization; includes report_settings explaining config
  get_cashflow_report     — same structure as PnL but expenses on actual cash
                            payment date, no amortization (cash-basis)

Payroll (module: "payroll"):
  list_payroll_documents  — salary payment documents
  get_payroll_document    — document with all employee lines

Investments (module: "investments"):
  get_investment_form_config — companies on/off, allowed return types
  list_invest_companies      — legal entities / projects dimension
  list_invest_returns        — payouts to investors (PnL invest_returns)
  list_project_investments   — capital invested into projects
  list_invest_payout_schedule — planned payout calendar (plan vs fact)

Budgets (module: "budgets"):
  list_budgets               — limits vs spend by category and period
  get_budget                 — one budget with utilization
  list_budget_spend_requests — requests counted toward a budget

Directories (modules: "vendors", "wallets"):
  list_vendors            — vendor directory; filter by kind or name
  list_wallets            — cash registers, bank accounts, card accounts
  list_active_users       — active tenant members with roles (admin/director only)

Tenant context (no module required):
  list_my_tenants         — tenants the current user belongs to
  get_my_role             — current user's roles in a tenant
  list_my_modules         — enabled + accessible modules for current user
  get_tenant_info         — tenant metadata (admin/director only)
  list_module_configs     — all module flags (admin/director only)
  list_user_roles         — user→role assignments (admin only)
  list_memberships        — all members (admin only)

════════════════════════════════════════════════════════════
ROLE PERMISSIONS
════════════════════════════════════════════════════════════
admin / director  — all modules
approver          — requests, vendors, contracts, notes
requester         — requests, vendors, contracts, notes
cashier           — requests, cash, corporate_card, wallets, vendors, contracts, notes, reports
accountant        — requests, bank, payroll, corporate_card, wallets, vendors, contracts, notes, reports
investor          — investments, reports

════════════════════════════════════════════════════════════
ERRORS AND FILTERING
════════════════════════════════════════════════════════════
- All tools return {"error": "..."} or [{"error": "..."}] on failure.
  Always check for the "error" key before using results.
- Date filters: YYYY-MM-DD only.
- limit: default 50, max 200 (max 500 for list_vendors).
- All data is strictly scoped to the given tenant_id.
""",
)

tool = django_mcp_tool(mcp)


def _err(msg: str) -> dict:
    return {"error": msg}


def _list_err(msg: str) -> list:
    return [{"error": msg}]


def _parse_bool_filter(value: str) -> bool | None:
    raw = (value or "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return None


# ---------------------------------------------------------------------------
# Discovery — call this first
# ---------------------------------------------------------------------------

@tool
def list_my_tenants() -> list:
    """List all active tenants the current user belongs to.

    Call this first to discover available tenant IDs and names before
    using any other tool that requires a tenant_id.
    """
    try:
        return cfg_tools.list_my_tenants()
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def get_my_role(tenant_id: int) -> dict:
    """Return the current user's roles in a tenant.

    Call after list_my_tenants() to understand what actions are available.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.get_my_role(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool
def list_my_modules(tenant_id: int) -> list:
    """List modules that are enabled AND accessible to the current user.

    Use this before calling finance/directory tools to know what's available.

    Args:
        tenant_id: Tenant primary key.
    """
    try:
        return cfg_tools.list_my_modules(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Requests (заявки)
# ---------------------------------------------------------------------------

@tool
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
    """List payment requests (заявки на оплату) for a tenant with optional filters.

    A request is a payment order initiated by an employee and routed through
    a multi-step approval chain before being paid. Each request has an amount,
    currency, vendor, category, urgency, and a current status reflecting where
    it is in the approval workflow.

    Status lifecycle:
      DRAFT     — saved but not yet submitted for approval
      1–5       — in approval (step number depends on tenant config)
      APPROVED  — all approvers signed off, awaiting payment
      PAYED     — payment confirmed by cashier/accountant
      REJECTED  — declined at some approval step

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        status: Filter by status. One of: DRAFT, 1, 2, 3, 4, 5, APPROVED, PAYED, REJECTED.
        currency: Filter by currency. One of: UZS, USD, EUR, RUB.
        payment_type: How payment is made. One of:
            "Наличные" (cash),
            "Перечисление" (bank transfer),
            "Пополнение" (top-up / prepayment),
            "Платежная карта" (corporate card).
        urgency: One of: "Низко" (low), "Обычно" (normal), "Срочно" (urgent).
        date_from: Filter by creation date >= YYYY-MM-DD.
        date_to: Filter by creation date <= YYYY-MM-DD.
        limit: Max records to return (1–200, default 50).
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


@tool
def get_request(tenant_id: int, request_id: int) -> dict:
    """Get full details of a single payment request by ID.

    Returns all request fields plus the approval chain: each step shows
    the approver's name, their decision (approved / rejected / pending),
    comment, and timestamp. Use this after list_requests to drill into
    a specific request.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        request_id: Request primary key (get from list_requests).
    """
    try:
        return req_tools.get_request(tenant_id=tenant_id, request_id=request_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool
def list_request_categories(tenant_id: int) -> list:
    """List active payment request categories configured for a tenant.

    Categories classify what a request is for (e.g. "Аренда", "Маркетинг",
    "Зарплата"). Use this to understand available categories before
    filtering or explaining requests to the user.

    Required roles: admin, director, approver, requester, accountant, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
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

@tool
def list_cash_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    currency: str = "",
    limit: int = 50,
) -> list:
    """[RECONCILIATION ONLY] Raw cash register outflows for a tenant.

    WARNING: Do NOT use this to answer questions about expenses — use
    list_requests instead. This tool returns raw cashier records used
    to verify that every cash payment has a matching request (заявка).
    Only call this when the user explicitly asks for raw cash data.

    Required roles: admin, director, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        date_from: Filter expense_at >= this date (YYYY-MM-DD).
        date_to: Filter expense_at <= this date (YYYY-MM-DD).
        currency: One of: UZS, USD, EUR, RUB.
        limit: Max records (1–200, default 50).
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


@tool
def list_cash_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """Raw cash inflows (receipts) for a tenant.

    Safe to query directly — revenues are not tracked via requests.
    Use this to see money coming into the cash register (e.g. client
    payments, refunds received, cash deposits).

    Required roles: admin, director, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        date_from: Filter revenue_at >= this date (YYYY-MM-DD).
        date_to: Filter revenue_at <= this date (YYYY-MM-DD).
        limit: Max records (1–200, default 50).
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


@tool
def list_bank_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """[RECONCILIATION ONLY] Raw bank debit transactions for a tenant.

    WARNING: Do NOT use this to answer questions about expenses — use
    list_requests instead. This tool returns raw bank statement debits
    used to verify that every bank payment has a matching request (заявка).
    Only call this when the user explicitly asks for raw bank transaction data.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        date_from: Filter doc_date >= this date (YYYY-MM-DD).
        date_to: Filter doc_date <= this date (YYYY-MM-DD).
        limit: Max records (1–200, default 50).
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


@tool
def list_bank_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """Raw bank credit transactions (incoming transfers) for a tenant.

    Safe to query directly — revenues are not tracked via requests.
    Use this to see money arriving in the company's bank accounts
    (e.g. client payments, loan receipts, refunds from suppliers).

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        date_from: Filter doc_date >= this date (YYYY-MM-DD).
        date_to: Filter doc_date <= this date (YYYY-MM-DD).
        limit: Max records (1–200, default 50).
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


@tool
def list_card_expenses(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """[RECONCILIATION ONLY] Raw corporate card charges for a tenant.

    WARNING: Do NOT use this to answer questions about expenses — use
    list_requests instead. This tool returns raw card statement charges
    used to verify that every card payment has a matching request (заявка).
    Only call this when the user explicitly asks for raw card transaction data.

    Required roles: admin, director, accountant, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        date_from: Filter expense_at >= this date (YYYY-MM-DD).
        date_to: Filter expense_at <= this date (YYYY-MM-DD).
        limit: Max records (1–200, default 50).
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


@tool
def list_card_revenues(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
) -> list:
    """Raw corporate card credits (top-ups, refunds) for a tenant.

    Safe to query directly — revenues are not tracked via requests.
    Use this to see money loaded onto corporate cards or refunded back
    to the card (e.g. "Пополнение" from the company, merchant refunds).

    Required roles: admin, director, accountant, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        date_from: Filter revenue_at >= this date (YYYY-MM-DD).
        date_to: Filter revenue_at <= this date (YYYY-MM-DD).
        limit: Max records (1–200, default 50).
    """
    try:
        return fin_tools.list_card_revenues(
            tenant_id=tenant_id,
            date_from=date_from, date_to=date_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Reports — PnL and Cashflow
# ---------------------------------------------------------------------------

@tool
def get_pnl_report(tenant_id: int) -> dict:
    """Get the full Profit & Loss (PnL) report for a tenant.

    Builds the report directly from the database using the tenant's saved
    pnl_config settings. The response includes a report_settings block that
    explains exactly how the report was constructed (filters, buckets, etc.).

    ── Response structure ──────────────────────────────────────────────────
    {
      "revenue": [                     ← all income lines (bank + cash inflows)
        { "id", "date", "amount", "category", "purpose", "description" }
      ],
      "operational_expenses": [        ← operating costs (e.g. rent, salaries)
        { "id", "date", "amount", "category", "purpose", "description" }
      ],
      "other_expenses": [              ← non-operating costs (e.g. taxes, fines)
        { "id", "date", "amount", "category", "purpose", "description" }
      ],
      "invest_returns": [              ← founder / investor payouts
        { "id", "date", "amount", "category", "purpose", "description" }
      ],
      "metadata": { "start_month" },  ← report window start (YYYY-MM)
      "report_settings": {            ← FULL config used to build this report
        "start_month",                   first month included
        "cash_exclude_operations",       cash revenue ops excluded from income
        "request_exclude_categories",    request categories excluded from expenses
        "request_payment_types_for_pnl", payment types included as PnL expenses
        "payment_purpose_operational",   purposes → operational_expenses bucket
        "payment_purpose_other",         purposes → other_expenses bucket
        "payment_purpose_invest_returns",purposes → invest_returns bucket
        "invest_return_type_operational",invest return types → operational bucket
        "invest_return_type_other",      invest return types → other bucket
        "invest_return_type_invest_returns" invest return types → invest bucket
      }
    }
    ────────────────────────────────────────────────────────────────────────

    Key rule: expenses use billing_date from requests; amortized requests are
    spread across months according to their amortization schedule.

    Required roles: admin, director, accountant, cashier, investor (module: reports).

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
    """
    try:
        return fin_tools.get_pnl_report(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool
def get_cashflow_report(tenant_id: int) -> dict:
    """Get the full Cashflow report for a tenant.

    Same structure and config as get_pnl_report, but expenses use the actual
    cash payment date (payed_at / expense_year+month) instead of billing_date,
    and there is NO amortization — every expense appears once on the day money
    left the account.

    ── Response structure ──────────────────────────────────────────────────
    Identical shape to get_pnl_report:
    { "revenue", "operational_expenses", "other_expenses",
      "invest_returns", "metadata", "report_settings" }

    Each expense line: { "id", "date", "amount", "category", "purpose", "description" }
    ────────────────────────────────────────────────────────────────────────

    ── PnL vs Cashflow ─────────────────────────────────────────────────────
    PnL       — billing_date (accrual); amortized items spread across months.
    Cashflow  — actual payment date;    no amortization, cash-basis only.
    ────────────────────────────────────────────────────────────────────────

    Required roles: admin, director, accountant, cashier, investor (module: reports).

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
    """
    try:
        return fin_tools.get_cashflow_report(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool
def list_payroll_documents(tenant_id: int, limit: int = 50) -> list:
    """List payroll documents (ведомости) for a tenant.

    A payroll document is a salary payment batch — it groups multiple
    employee payment lines under one document with a period (month/year),
    status, and total amount. Use get_payroll_document to retrieve the
    individual lines (per-employee amounts).

    Statuses: DRAFT, APPROVED, PAYED.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        limit: Max records (1–200, default 50).
    """
    try:
        return fin_tools.list_payroll_documents(tenant_id=tenant_id, limit=limit)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def get_payroll_document(tenant_id: int, document_id: int) -> dict:
    """Get a payroll document and all its employee payment lines.

    Returns the document header (period, status, totals) plus an array
    of lines — one per employee — each showing the employee name,
    accrual amount, and payment amount. Use list_payroll_documents first
    to find the document_id.

    Required roles: admin, director, accountant.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        document_id: PayrollDocument primary key (get from list_payroll_documents).
    """
    try:
        return fin_tools.get_payroll_document(tenant_id=tenant_id, document_id=document_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Investments
# ---------------------------------------------------------------------------

@tool
def get_investment_form_config(tenant_id: int) -> dict:
    """Per-tenant investment settings before other investment tools.

    Returns whether company_id filters apply (uses_companies) and which
    return_type strings are allowed when filtering list_invest_returns.

    Required roles: admin, director, investor.

    Args:
        tenant_id: Tenant primary key (from list_my_tenants).
    """
    try:
        return inv_tools.get_investment_form_config(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool
def list_invest_companies(
    tenant_id: int,
    name_search: str = "",
    is_active: str = "",
    limit: int = 100,
) -> list:
    """List investment companies (юрлица / проекты) for grouping returns and schedules.

    Use name_search to find company_id for other investment tools.
    Empty is_active = all; "true" / "false" to filter active flag.

    Required roles: admin, director, investor.

    Args:
        tenant_id: Tenant primary key.
        name_search: Substring match on company name.
        is_active: "", "true", or "false".
        limit: Max rows (default 100, max 200).
    """
    try:
        active = _parse_bool_filter(is_active)
        return inv_tools.list_invest_companies(
            tenant_id=tenant_id,
            name_search=name_search,
            is_active=active,
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def list_invest_returns(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    return_type: str = "",
    recipient: str = "",
    company_id: int = 0,
    confirmed: str = "",
    limit: int = 50,
) -> list:
    """List investor payouts (выплаты инвесторам): dividends, interest, principal, etc.

    Primary outbound cash in the Investments module; hits PnL invest_returns
    by billing_date. return_type examples: дивиденды, проценты, доля_прибыли,
    тело_инвестиций. recipient: инвестор | партнер.

    Required roles: admin, director, investor.

    Args:
        tenant_id: Tenant primary key.
        date_from / date_to: Filter payout date (YYYY-MM-DD).
        return_type / recipient: Exact DB enum labels.
        company_id: Filter by InvestCompany id (0 = all).
        confirmed: "", "true", or "false".
        limit: Max rows (default 50, max 200).
    """
    try:
        return inv_tools.list_invest_returns(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            return_type=return_type,
            recipient=recipient,
            company_id=company_id,
            confirmed=_parse_bool_filter(confirmed),
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def list_project_investments(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    company_id: int = 0,
    confirmed: str = "",
    limit: int = 50,
) -> list:
    """List capital invested into projects (вложения в проекты), inbound vs returns.

    Required roles: admin, director, investor.

    Args:
        tenant_id: Tenant primary key.
        date_from / date_to: YYYY-MM-DD on investment date.
        company_id: 0 = all companies.
        confirmed: "", "true", or "false".
        limit: Max rows (default 50, max 200).
    """
    try:
        return inv_tools.list_project_investments(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            company_id=company_id,
            confirmed=_parse_bool_filter(confirmed),
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def list_invest_payout_schedule(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    company_id: int = 0,
    is_paid: str = "",
    limit: int = 50,
) -> list:
    """List planned investment payout schedule (график выплат).

    Compare is_paid and payment_amount with list_invest_returns for plan vs fact.

    Required roles: admin, director, investor.

    Args:
        tenant_id: Tenant primary key.
        date_from / date_to: Filter payout_date (YYYY-MM-DD).
        company_id: 0 = all.
        is_paid: "", "true", or "false".
        limit: Max rows (default 50, max 200).
    """
    try:
        return inv_tools.list_invest_payout_schedule(
            tenant_id=tenant_id,
            date_from=date_from,
            date_to=date_to,
            company_id=company_id,
            is_paid=_parse_bool_filter(is_paid),
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------

@tool
def list_budgets(
    tenant_id: int,
    year: int = 0,
    period: int = 0,
    category_name: str = "",
    is_active: str = "",
    limit: int = 100,
) -> list:
    """List budgets with spent_amount, remaining, utilization_pct for a period.

    Spend = sum of APPROVED + PAYED requests matching category, currency,
    and billing_date in the period (same as UI). period_type: monthly |
    quarterly | yearly. period is month 1–12 (quarterly uses month→quarter).

    year=0 and period=0 default to current year/month.

    Required roles: admin, director, accountant, approver.

    Args:
        tenant_id: Tenant primary key.
        year: Calendar year (0 = current).
        period: Month 1–12 (0 = current month).
        category_name: Exact request category name filter.
        is_active: "", "true", or "false".
        limit: Max budgets (default 100, max 200).
    """
    try:
        return bud_tools.list_budgets(
            tenant_id=tenant_id,
            year=year or None,
            period=period or None,
            category_name=category_name,
            is_active=_parse_bool_filter(is_active),
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def get_budget(
    tenant_id: int,
    budget_id: int,
    year: int = 0,
    period: int = 0,
) -> dict:
    """Get one budget with utilization for a period (use list_budgets for budget_id).

    Required roles: admin, director, accountant, approver.

    Args:
        tenant_id: Tenant primary key.
        budget_id: Budget primary key.
        year / period: Same as list_budgets (0 = current).
    """
    try:
        return bud_tools.get_budget(
            tenant_id=tenant_id,
            budget_id=budget_id,
            year=year or None,
            period=period or None,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool
def list_budget_spend_requests(
    tenant_id: int,
    budget_id: int,
    year: int = 0,
    period: int = 0,
    limit: int = 100,
) -> list:
    """List payment requests that count toward a budget's spend in the period.

    Drill-down after list_budgets / get_budget when utilization is high.

    Required roles: admin, director, accountant, approver.

    Args:
        tenant_id: Tenant primary key.
        budget_id: Budget primary key.
        year / period: Evaluation period (0 = current).
        limit: Max requests (default 100, max 200).
    """
    try:
        return bud_tools.list_budget_spend_requests(
            tenant_id=tenant_id,
            budget_id=budget_id,
            year=year or None,
            period=period or None,
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Reference directories (справочники)
# ---------------------------------------------------------------------------

@tool
def list_vendors(
    tenant_id: int,
    kind: str = "",
    name_search: str = "",
    limit: int = 100,
) -> list:
    """List vendors (контрагенты / получатели) from the tenant directory.

    Vendors are the recipients of payment requests. Each vendor has a kind:
      • "cash"     — paid in cash via cashier (Наличные payment type)
      • "transfer" — paid by bank transfer or card (Перечисление / Платежная карта)

    Use name_search to find a specific vendor before looking at their requests.
    Vendors are referenced on every payment request, so this directory is the
    starting point for understanding who the company pays.

    Required roles: admin, director, approver, requester, cashier, accountant.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
        kind: Filter by payment kind. One of: cash, transfer.
        name_search: Case-insensitive substring match on vendor name.
        limit: Max records (1–500, default 100).
    """
    try:
        return dir_tools.list_vendors(
            tenant_id=tenant_id, kind=kind, name_search=name_search, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def list_active_users(tenant_id: int) -> list:
    """List active members of a tenant with their roles.

    Use this to resolve user names when displaying request approvers,
    payroll recipients, or to find who holds a given role in the tenant.
    Returns only id, full_name, username, and roles — no passwords,
    emails, or other sensitive fields.

    Required roles: admin, director.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
    """
    try:
        return dir_tools.list_active_users(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool
def list_wallets(tenant_id: int) -> list:
    """List all wallets (счета / кассы) for a tenant.

    A wallet is a named account or register that holds funds. Types:
      • cash    — physical cash register operated by a cashier
      • bank    — company bank account for wire transfers
      • card    — corporate card account

    Wallets appear on cash/bank/card transactions. Use this to understand
    which accounts the tenant operates and their currencies.

    Required roles: admin, director, accountant, cashier.

    Args:
        tenant_id: Tenant primary key (get from list_my_tenants).
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

# ---------------------------------------------------------------------------
# Tenant configuration
# ---------------------------------------------------------------------------

@tool
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


@tool
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


@tool
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


@tool
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
