"""
Kolberg MCP Server — one company (tenant) per connector.

Served over streamable HTTP at https://<tenant>.<BASE_DOMAIN>/mcp
(see apps/mcp_server/http/app.py and config/asgi.py). The tenant comes from the
Host subdomain; tools never take tenant_id. list_tools/call_tool expose only
tools allowed by the tenant's enabled modules and the user's roles.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from apps.mcp_server.access import Access
from apps.mcp_server.django_tools import TOOL_ACCESS, django_mcp_tool
from apps.mcp_server.tenant_context import current_tenant
from apps.mcp_server.tools import (
    requests as req_tools,
    finance as fin_tools,
    directories as dir_tools,
    integrations as int_tools,
    tenant_config as cfg_tools,
    investments as inv_tools,
    budgets as bud_tools,
    tasks as task_tools,
    contracts as contract_tools,
    clients_debt as debt_tools,
    cash_withdrawals as cw_tools,
    notes as note_tools,
)


def _visible_tool_names_sync() -> set[str]:
    from apps.mcp_server.access import visible_tools
    from apps.mcp_server.auth import _decode_token, _get_token

    try:
        user_id = _decode_token(_get_token())
    except PermissionError:
        return set()
    return visible_tools(TOOL_ACCESS, user_id=user_id, tenant_id=current_tenant().id)


class TenantScopedMCPServer(MCPServer):
    """Hides tools the caller may not use; a hidden tool behaves as nonexistent."""

    async def _visible(self) -> set[str]:
        from asgiref.sync import sync_to_async

        return await sync_to_async(_visible_tool_names_sync, thread_sensitive=True)()

    async def list_tools(self):
        visible = await self._visible()
        return [t for t in await super().list_tools() if t.name in visible]

    async def call_tool(self, name, arguments, context=None):
        if name not in await self._visible():
            raise ToolError(f"Unknown tool: {name}")
        return await super().call_tool(name, arguments, context)


mcp = TenantScopedMCPServer(
    name="Kolberg Data Server",
    instructions="""
Kolberg is a financial management platform. This connector is bound to ONE
company (tenant); every tool works on that company only — call
get_current_tenant() to see which one. You only see the tools the current user
may use (enabled modules × roles). Everything is read-only except the tasks
tools (create_task, update_task_status, add_task_comment, edit_task, delete_task).

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
  • For totals ("сколько потратили на X", "расходы по категориям / месяцам /
    поставщикам") use summarize_requests — it sums on the server, so do not
    page through list_requests and add amounts up yourself.
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
ERRORS AND FILTERING
════════════════════════════════════════════════════════════
- All tools return {"error": "..."} or [{"error": "..."}] on failure.
  Always check for the "error" key before using results.
- Date filters: YYYY-MM-DD only.
- limit: default 50, max 200 (max 500 for list_vendors).
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

@tool(access=Access.always())
def get_current_tenant() -> dict:
    """Return the company (tenant) this connector is bound to.

    Every other tool works on this company only. Returns id, name, subdomain.
    """
    tenant = current_tenant()
    return {"id": tenant.id, "name": tenant.name, "subdomain": tenant.subdomain}


@tool(access=Access.always())
def get_my_role(tenant_id: int) -> dict:
    """Return the current user's roles in a tenant.

    Call first to understand what actions are available.
    """
    try:
        return cfg_tools.get_my_role(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.always())
def list_my_modules(tenant_id: int) -> list:
    """List modules that are enabled AND accessible to the current user.

    Use this before calling finance/directory tools to know what's available.
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

@tool(access=Access.module("requests"))
def list_requests(
    tenant_id: int,
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
    category: str = "",
    vendor: str = "",
    contract_id: int = 0,
    search: str = "",
    billing_date_from: str = "",
    billing_date_to: str = "",
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

    Args:
        status: Filter by status. One of: DRAFT, 1, 2, 3, 4, 5, APPROVED, PAYED, REJECTED,
            or several comma-separated (e.g. "APPROVED,PAYED").
            Deleted requests are never returned.
        currency: Filter by currency. One of: UZS, USD, EUR, RUB.
        payment_type: How payment is made. One of:
            "Наличные" (cash),
            "Перечисление" (bank transfer),
            "Пополнение" (top-up / prepayment),
            "Платежная карта" (corporate card),
            "Начисление ЗП" (payroll).
        urgency: One of: "Низко" (low), "Обычно" (normal), "Срочно" (urgent).
        date_from: Filter by creation date >= YYYY-MM-DD.
        date_to: Filter by creation date <= YYYY-MM-DD.
        limit: Max records to return (1–200, default 50).
        category: Exact category name, case-insensitive (see list_request_categories).
        vendor: Substring of the vendor name.
        contract_id: Only requests linked to this contract (see list_contracts).
        search: Substring of the description or payment purpose.
        billing_date_from: Filter by billing date (the month the expense belongs to) >= YYYY-MM-DD.
        billing_date_to: Filter by billing date <= YYYY-MM-DD.
    """
    try:
        return req_tools.list_requests(
            tenant_id=tenant_id, status=status,
            currency=currency, payment_type=payment_type, urgency=urgency,
            date_from=date_from, date_to=date_to, limit=limit,
            category=category, vendor=vendor, contract_id=contract_id, search=search,
            billing_date_from=billing_date_from, billing_date_to=billing_date_to,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.module("requests"))
def summarize_requests(
    tenant_id: int,
    group_by: str = "category",
    status: str = "",
    currency: str = "",
    payment_type: str = "",
    urgency: str = "",
    category: str = "",
    vendor: str = "",
    contract_id: int = 0,
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    billing_date_from: str = "",
    billing_date_to: str = "",
    limit: int = 100,
) -> dict:
    """Totals of payment requests grouped by category, vendor, month, status, payment type or currency.

    Use this for "how much was spent on X / by month / per vendor" instead of
    adding up list_requests pages. Sums are computed on the server.

    Every group is split by currency (amounts in different currencies are never
    added together). Returns:
      groups             — [{key, currency, count, total}], largest total first
      groups_total       — number of groups before `limit`
      totals_by_currency — [{currency, count, total}] over all matching requests

    For actual spending pass status="PAYED"; for spending plus what is about to
    be paid pass status="APPROVED,PAYED". Without status all non-deleted
    requests are counted, including drafts and rejected ones.

    Args:
        group_by: category | vendor | month | status | payment_type | currency.
            month groups by billing_date (the month the expense belongs to), key "YYYY-MM".
        status, currency, payment_type, urgency, category, vendor, contract_id,
        search, date_from, date_to, billing_date_from, billing_date_to:
            the same filters as list_requests.
        limit: Max groups to return (1–200, default 100).
    """
    try:
        return req_tools.summarize_requests(
            tenant_id=tenant_id, group_by=group_by, status=status,
            currency=currency, payment_type=payment_type, urgency=urgency,
            category=category, vendor=vendor, contract_id=contract_id, search=search,
            date_from=date_from, date_to=date_to,
            billing_date_from=billing_date_from, billing_date_to=billing_date_to,
            limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("requests"))
def get_request(tenant_id: int, request_id: int) -> dict:
    """Get full details of a single payment request by ID.

    Returns all request fields plus the approval chain: each step shows
    the approver's name, their decision (approved / rejected / pending),
    comment, and timestamp. Use this after list_requests to drill into
    a specific request.

    Args:
        request_id: Request primary key (get from list_requests).
    """
    try:
        return req_tools.get_request(tenant_id=tenant_id, request_id=request_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("requests"))
def list_request_categories(tenant_id: int) -> list:
    """List active payment request categories configured for a tenant.

    Categories classify what a request is for (e.g. "Аренда", "Маркетинг",
    "Зарплата"). Use this to understand available categories before
    filtering or explaining requests to the user.
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

@tool(access=Access.module("cash"))
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

    Args:
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


@tool(access=Access.module("cash"))
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

    Args:
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


@tool(access=Access.module("bank"))
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

    Args:
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


@tool(access=Access.module("bank"))
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

    Args:
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


@tool(access=Access.module("corporate_card"))
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

    Args:
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


@tool(access=Access.module("corporate_card"))
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

    Args:
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

@tool(access=Access.module("reports"))
def get_pnl_report(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    aggregate: bool = False,
) -> dict:
    """Get the Profit & Loss (PnL) report for a tenant.

    Builds the report directly from the database using the tenant's saved
    pnl_config settings. The response includes a report_settings block that
    explains exactly how the report was constructed (filters, buckets, etc.).

    ⚠ Without date_from/date_to or aggregate=True this returns EVERY line
    since pnl_config.start_month — for a tenant with a long history that can
    be thousands of rows. Prefer narrowing the window and/or aggregate=True
    unless you actually need individual line items.

    ── Response structure (aggregate=False, default) ───────────────────────
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

    ── Response structure (aggregate=True) ─────────────────────────────────
    Each of "revenue" / "operational_expenses" / "other_expenses" /
    "invest_returns" collapses from a line-item list to:
    { "total", "count", "by_month": {"YYYY-MM": amount, ...},
      "by_category": {category: amount, ...} }
    "metadata" and "report_settings" are unchanged; "aggregated": true is added.
    ────────────────────────────────────────────────────────────────────────

    Key rule: expenses use billing_date from requests; amortized requests are
    spread across months according to their amortization schedule.

    Args:
        date_from: Optional ISO date (YYYY-MM-DD) — drop lines before this date.
        date_to: Optional ISO date (YYYY-MM-DD) — drop lines after this date.
        aggregate: If True, return totals per bucket (by_month, by_category,
            count) instead of individual line items. Default False.
    """
    try:
        return fin_tools.get_pnl_report(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to, aggregate=aggregate
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("reports"))
def get_cashflow_report(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    aggregate: bool = False,
) -> dict:
    """Get the Cashflow report for a tenant.

    Same structure as get_pnl_report, built with the tenant's own Cashflow rules (cashflow_config); expenses use the actual
    cash payment date (payed_at / expense_year+month) instead of billing_date,
    and there is NO amortization — every expense appears once on the day money
    left the account.

    ⚠ Without date_from/date_to or aggregate=True this returns EVERY line
    since cashflow_config.start_month — for a tenant with a long history that can
    be thousands of rows. Prefer narrowing the window and/or aggregate=True
    unless you actually need individual line items.

    ── Response structure ──────────────────────────────────────────────────
    Identical shape to get_pnl_report, including the aggregate=True variant:
    { "revenue", "operational_expenses", "other_expenses",
      "invest_returns", "metadata", "report_settings" }

    Each expense line: { "id", "date", "amount", "category", "purpose", "description" }
    ────────────────────────────────────────────────────────────────────────

    ── PnL vs Cashflow ─────────────────────────────────────────────────────
    PnL       — billing_date (accrual); amortized items spread across months.
    Cashflow  — actual payment date;    no amortization, cash-basis only.
    ────────────────────────────────────────────────────────────────────────

    Args:
        date_from: Optional ISO date (YYYY-MM-DD) — drop lines before this date.
        date_to: Optional ISO date (YYYY-MM-DD) — drop lines after this date.
        aggregate: If True, return totals per bucket (by_month, by_category,
            count) instead of individual line items. Default False.
    """
    try:
        return fin_tools.get_cashflow_report(
            tenant_id=tenant_id, date_from=date_from, date_to=date_to, aggregate=aggregate
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("payroll"))
def list_payroll_documents(
    tenant_id: int,
    status: str = "",
    kind: str = "",
    period_from: str = "",
    period_to: str = "",
    limit: int = 50,
) -> list:
    """List payroll documents (ведомости начисления ЗП) for a tenant.

    A payroll document is a salary accrual batch: lines per employee grouped
    under one document for a period. Each row returns:
      id, doc_id, label, status, kind, period_month, source, payout_mode,
      created_at, total_sum (accrued), paid_total (paid out via the portal),
      lines_count, has_request / has_paid_request / matched_request_id
      (the "Начисление ЗП" payment request linked to the document).

    Statuses: draft (being edited), accepted (accrual accepted, being paid),
    closed (fully paid or closed underpaid), cancelled.
    Kinds: salary, advance, bonus. Documents imported from n8n may have no
    kind / period_month and payout_mode "legacy" (paid outside the portal,
    so paid_total stays 0).

    Use get_payroll_document for per-employee amounts.

    Args:
        status: One of: draft, accepted, closed, cancelled.
        kind: One of: salary, advance, bonus.
        period_from: period_month >= YYYY-MM-DD (excludes documents without a period).
        period_to: period_month <= YYYY-MM-DD (excludes documents without a period).
        limit: Max records (1–200, default 50).
    """
    try:
        return fin_tools.list_payroll_documents(
            tenant_id=tenant_id, status=status, kind=kind,
            period_from=period_from, period_to=period_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.module("payroll"))
def get_payroll_document(tenant_id: int, document_id: int) -> dict:
    """Get one payroll document with lines and per-employee payout progress.

    Returns the same header fields as list_payroll_documents plus:
      total_sum / paid_total / remaining_total — accrued, paid, still to pay
      current_request — linked "Начисление ЗП" request {id, status} or null
      closed_underpaid_at, close_comment — set when closed without full payment
      lines     — accrual lines: employee, employee_id, item, description, sum,
                  days_plan, days_fact, period_start, period_end, approval
      employees — per employee: employee_id, full_name, accrued, paid, remaining
      payouts   — cash expenses the document was paid out with:
                  cash_expense_id, date, amount, wallet_id

    Use list_payroll_documents first to find the document_id.

    Args:
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

@tool(access=Access.module("investments"))
def get_investment_form_config(tenant_id: int) -> dict:
    """Per-tenant investment settings before other investment tools.

    Returns whether company_id filters apply (uses_companies) and which
    return_type strings are allowed when filtering list_invest_returns.
    """
    try:
        return inv_tools.get_investment_form_config(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("investments"))
def list_invest_companies(
    tenant_id: int,
    name_search: str = "",
    is_active: str = "",
    limit: int = 100,
) -> list:
    """List investment companies (юрлица / проекты) for grouping returns and schedules.

    Use name_search to find company_id for other investment tools.
    Empty is_active = all; "true" / "false" to filter active flag.

    Args:
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


@tool(access=Access.module("investments"))
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

    Args:
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


@tool(access=Access.module("investments"))
def list_project_investments(
    tenant_id: int,
    date_from: str = "",
    date_to: str = "",
    company_id: int = 0,
    confirmed: str = "",
    limit: int = 50,
) -> list:
    """List capital invested into projects (вложения в проекты), inbound vs returns.

    Args:
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


@tool(access=Access.module("investments"))
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

    Args:
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

@tool(access=Access.module("budgets"))
def list_budgets(
    tenant_id: int,
    year: int = 0,
    period: int = 0,
    category_name: str = "",
    is_active: str = "",
    limit: int = 100,
    payment_purpose: str = "",
) -> list:
    """List budgets with spent_amount, remaining, utilization_pct for a period.

    A budget is set either on a request category (category_name) or on a
    payment purpose (payment_purpose); the other one is null.
    Spend = sum of APPROVED + PAYED requests matching that category or
    purpose, currency, and billing_date in the period (same as UI). period_type: monthly |
    quarterly | yearly. period is month 1–12 (quarterly uses month→quarter).

    year=0 and period=0 default to current year/month.

    Args:
        year: Calendar year (0 = current).
        period: Month 1–12 (0 = current month).
        category_name: Exact request category name filter.
        payment_purpose: Exact payment purpose filter.
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
            payment_purpose=payment_purpose,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.module("budgets"))
def get_budget(
    tenant_id: int,
    budget_id: int,
    year: int = 0,
    period: int = 0,
) -> dict:
    """Get one budget with utilization for a period (use list_budgets for budget_id).

    Args:
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


@tool(access=Access.module("budgets"))
def list_budget_spend_requests(
    tenant_id: int,
    budget_id: int,
    year: int = 0,
    period: int = 0,
    limit: int = 100,
) -> list:
    """List payment requests that count toward a budget's spend in the period.

    Drill-down after list_budgets / get_budget when utilization is high.

    Args:
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
# Tasks (задачи)
# ---------------------------------------------------------------------------

@tool(access=Access.module("tasks"))
def list_my_tasks(
    tenant_id: int,
    status: str = "",
    limit: int = 50,
) -> list:
    """List tasks visible to the current user for a tenant.

    Admins and directors see all tasks in the tenant. Every other role
    sees only tasks assigned to themselves. Use this to check your
    pending work or to audit outstanding tasks as a manager.

    Status values: new | in_progress | done

    Args:
        status: Filter by status. One of: new, in_progress, done.
        limit: Max tasks to return (1–200, default 50).
    """
    try:
        return task_tools.list_tasks(tenant_id=tenant_id, status=status, limit=limit)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks"))
def get_task(tenant_id: int, task_id: int) -> dict:
    """Get full details of a single task including its comment thread.

    Returns all task fields plus an ordered list of comments. Comments
    are append-only — they record the discussion history between the
    assignee and admins/directors.

    Access rules: assignee can always read their own task; admins and
    directors can read any task in the tenant.

    Args:
        task_id: Task primary key (get from list_my_tasks).
    """
    try:
        return task_tools.get_task_detail(tenant_id=tenant_id, task_id=task_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks", admin_or_director=True))
def create_task(
    tenant_id: int,
    assignee_id: int,
    title: str,
    description: str = "",
) -> dict:
    """Create a task and assign it to a tenant member.

    Only admins and directors can use this tool — it allows assigning tasks
    to any active user in the tenant. Use this to delegate work, create
    follow-up tasks after reviewing financials, or set up ad-hoc assignments.

    Args:
        assignee_id: User ID of the person who will own the task (get from list_assignee_candidates).
        title: Short task title (max 255 chars).
        description: Optional detailed description.
    """
    try:
        return task_tools.create_task(
            tenant_id=tenant_id,
            assignee_id=assignee_id,
            title=title,
            description=description,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks"))
def update_task_status(
    tenant_id: int,
    task_id: int,
    new_status: str,
) -> dict:
    """Change the status of a task.

    Allowed transitions: new → in_progress | done; in_progress → new | done.
    Tasks in 'done' status cannot be transitioned further.

    Admins and directors can update any task in the tenant.
    Other roles can only update tasks assigned to themselves.

    Status values: new | in_progress | done

    Args:
        task_id: Task primary key (get from list_my_tasks).
        new_status: Target status — one of: new, in_progress, done.
    """
    try:
        return task_tools.update_task_status(
            tenant_id=tenant_id,
            task_id=task_id,
            new_status=new_status,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks"))
def add_task_comment(
    tenant_id: int,
    task_id: int,
    body: str,
) -> dict:
    """Post a comment on a task.

    Admins and directors can comment on any task. Other roles can only
    comment on tasks assigned to themselves.

    Args:
        task_id: Task primary key (get from list_my_tasks).
        body: Comment text (must not be empty).
    """
    try:
        return task_tools.add_task_comment(
            tenant_id=tenant_id,
            task_id=task_id,
            body=body,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks"))
def edit_task(
    tenant_id: int,
    task_id: int,
    title: str = "",
    description: str = "",
    assignee_id: int = 0,
) -> dict:
    """Update a task's title, description, or assignee.

    Only the task creator, admin, or director can edit a task.
    Pass only the fields you want to change — omitted fields stay unchanged.
    Reassigning to a different user requires admin or director role.

    Args:
        task_id: Task primary key (get from list_my_tasks).
        title: New title (omit to keep current).
        description: New description (omit to keep current).
        assignee_id: New assignee user ID (0 = keep current; get from list_assignee_candidates).
    """
    try:
        return task_tools.edit_task(
            tenant_id=tenant_id,
            task_id=task_id,
            title=title,
            description=description,
            assignee_id=assignee_id,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks"))
def delete_task(tenant_id: int, task_id: int) -> dict:
    """Delete a task permanently.

    Only the task creator, admin, or director can delete a task.

    Args:
        task_id: Task primary key (get from list_my_tasks).
    """
    try:
        return task_tools.delete_task(tenant_id=tenant_id, task_id=task_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.module("tasks"))
def list_assignee_candidates(tenant_id: int) -> list:
    """List users who can be assigned a task in this tenant.

    Admins and directors see all active members.
    Other roles see only themselves (they may only self-assign via the web UI).

    Use this before create_task or edit_task to find valid assignee_id values.
    """
    try:
        return task_tools.list_assignee_candidates(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Reference directories (справочники)
# ---------------------------------------------------------------------------

@tool(access=Access.module("vendors"))
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

    Args:
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


@tool(access=Access.admin_or_director())
def list_active_users(tenant_id: int) -> list:
    """List active members of a tenant with their roles.

    Use this to resolve user names when displaying request approvers,
    payroll recipients, or to find who holds a given role in the tenant.
    Returns only id, full_name, username, and roles — no passwords,
    emails, or other sensitive fields.
    """
    try:
        return dir_tools.list_active_users(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.module("wallets"))
def list_wallets(tenant_id: int) -> list:
    """List all wallets (счета / кассы) for a tenant.

    A wallet is a named account or register that holds funds. wallet_type:
      • cash           — physical cash register operated by a cashier
      • bank           — company bank account for wire transfers
      • corporate_card — corporate card account

    Wallets appear on cash/bank/card transactions. Use this to understand
    which accounts the tenant operates, their currencies and how much money
    is on each of them.

    current_balance — balance right now (as shown in the portal): the
    balance carried over at Jan 1 plus all movements of the current year.
    Use it to answer "сколько денег на счетах / в кассе"; do not sum raw
    transactions yourself.
    """
    try:
        return dir_tools.list_wallets(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Contracts (договоры)
# ---------------------------------------------------------------------------

@tool(access=Access.module("contracts"))
def list_contracts(
    tenant_id: int,
    status: str = "",
    vendor_id: int = 0,
    search: str = "",
    active_on: str = "",
    expires_from: str = "",
    expires_to: str = "",
    limit: int = 50,
) -> list:
    """List vendor contracts (договоры) with how much has already been paid on each.

    paid_total — sum of PAYED requests linked to the contract, in the contract's
    currency; remaining — contract_amount minus paid_total (null when the
    contract has no amount).

    Args:
        status: accepted | refused | expired. "expired" = accepted with date_to in the past;
            "accepted" = currently valid (not expired).
        vendor_id: Contracts with this vendor (see list_vendors).
        search: Substring of the contract number or vendor name.
        active_on: Contracts valid on this date (YYYY-MM-DD).
        expires_from / expires_to: date_to within this range (YYYY-MM-DD) — e.g.
            "which contracts expire this month".
        limit: Max records (1–200, default 50).
    """
    try:
        return contract_tools.list_contracts(
            tenant_id=tenant_id, status=status, vendor_id=vendor_id, search=search,
            active_on=active_on, expires_from=expires_from, expires_to=expires_to, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.module("contracts"))
def get_contract(tenant_id: int, contract_id: int) -> dict:
    """Get one contract with its terms (contract_terms) and every request linked to it.

    Args:
        contract_id: Contract primary key (get from list_contracts).
    """
    try:
        return contract_tools.get_contract(tenant_id=tenant_id, contract_id=contract_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Clients debt (дебиторка клиентов)
# ---------------------------------------------------------------------------

@tool(access=Access.module("clients_debt"))
def get_client_debts(
    tenant_id: int,
    doc_type: str = "",
    client_search: str = "",
    as_of: str = "",
    limit: int = 200,
) -> dict:
    """Client debts (дебиторская задолженность) from the latest imported snapshot.

    Debts are imported as dated snapshots. Only the latest snapshot of each
    doc_type is used — never add up several snapshots. Returns:
      snapshots     — [{doc_type, snapshot_at, clients_count, total_debt}]
      clients       — per-client rows (debt_sum etc.), largest debt first
      clients_total — number of client rows before `limit`

    Args:
        doc_type: Only this snapshot type (see the doc_type values in `snapshots`).
        client_search: Substring of the client name or client id.
        as_of: Use the latest snapshots taken on or before this date (YYYY-MM-DD) —
            e.g. "what was the debt at the start of the month".
        limit: Max client rows (1–500, default 200).
    """
    try:
        return debt_tools.get_client_debts(
            tenant_id=tenant_id, doc_type=doc_type, client_search=client_search,
            as_of=as_of, limit=limit,
        )
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Cash withdrawals (снятие наличных)
# ---------------------------------------------------------------------------

@tool(access=Access.admin_or_director())
def list_cash_withdrawal_receipts(tenant_id: int, status: str = "pending", limit: int = 50) -> list:
    """Paid cash-withdrawal requests and whether the cash was confirmed as received at the register.

    After a withdrawal request is PAYED, a cashier must confirm in Telegram that
    the cash arrived. Pending receipts are money that left the bank but has not
    yet been confirmed at a cash register — useful for control.

    Args:
        status: pending (default) | confirmed | closed (closed without a cash revenue) | all.
        limit: Max records (1–200, default 50), oldest first.
    """
    try:
        return cw_tools.list_cash_withdrawal_receipts(tenant_id=tenant_id, status=status, limit=limit)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


# ---------------------------------------------------------------------------
# Notes (заметки)
# ---------------------------------------------------------------------------

@tool(access=Access.module("notes"))
def list_my_notes(
    tenant_id: int,
    target_type: str = "",
    target_id: int = 0,
    limit: int = 50,
) -> list:
    """Notes the current user sent or received about a request or a cash/bank operation.

    Notes are personal messages (delivered via Telegram), so only notes where
    the current user is the author or the recipient are returned.

    Args:
        target_type: request | cash | bank.
        target_id: Id of the request / cash operation / bank operation.
        limit: Max records (1–200, default 50), newest first.
    """
    try:
        return note_tools.list_my_notes(
            tenant_id=tenant_id, target_type=target_type, target_id=target_id, limit=limit,
        )
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

@tool(access=Access.admin_or_director())
def get_tenant_info(tenant_id: int) -> dict:
    """Get public metadata for a tenant.
    """
    try:
        return cfg_tools.get_tenant_info(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"Unexpected error: {e}")


@tool(access=Access.admin_or_director())
def list_module_configs(tenant_id: int) -> list:
    """List all module enable/disable flags for a tenant.
    """
    try:
        return cfg_tools.list_module_configs(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.admin())
def list_user_roles(tenant_id: int) -> list:
    """List all user-role assignments for a tenant (admin only).
    """
    try:
        return cfg_tools.list_user_roles(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")


@tool(access=Access.admin())
def list_memberships(tenant_id: int) -> list:
    """List all tenant memberships (admin only).
    """
    try:
        return cfg_tools.list_memberships(tenant_id=tenant_id)
    except (PermissionError, ValueError) as e:
        return _list_err(str(e))
    except Exception as e:
        return _list_err(f"Unexpected error: {e}")

