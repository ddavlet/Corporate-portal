def list_modules():
    """
    Central module registry used by `/api/modules/` and tenant-admin config APIs.
    Each module app should expose a `MODULE_KEY` and `display_name`.
    """
    # Import only module registry metadata (no ORM model imports).
    from apps.modules.requests.registry import MODULE_KEY as REQUESTS_KEY, display_name as REQUESTS_NAME
    from apps.modules.vendors.registry import MODULE_KEY as VENDORS_KEY, display_name as VENDORS_NAME
    from apps.modules.cashier.registry import MODULE_KEY as CASHIER_KEY, display_name as CASHIER_NAME
    from apps.modules.bank_expenses.registry import MODULE_KEY as BANK_EXPENSES_KEY, display_name as BANK_EXPENSES_NAME
    from apps.modules.corporate_card.registry import MODULE_KEY as CORPORATE_CARD_KEY, display_name as CORPORATE_CARD_NAME
    from apps.modules.notes.registry import MODULE_KEY as NOTES_KEY, display_name as NOTES_NAME
    from apps.modules.n8n_integration.registry import MODULE_KEY as N8N_KEY, display_name as N8N_NAME
    from apps.modules.telegram_approvals.registry import MODULE_KEY as TG_APPROVALS_KEY, display_name as TG_APPROVALS_NAME
    from apps.modules.payroll.registry import MODULE_KEY as PAYROLL_KEY, display_name as PAYROLL_NAME
    from apps.modules.wallets.registry import MODULE_KEY as WALLETS_KEY, display_name as WALLETS_NAME
    from apps.modules.reports.registry import MODULE_KEY as REPORTS_KEY, display_name as REPORTS_NAME
    from apps.modules.clients_debt.registry import MODULE_KEY as CLIENTS_DEBT_KEY, display_name as CLIENTS_DEBT_NAME
    from apps.modules.investments.registry import MODULE_KEY as INVESTMENTS_KEY, display_name as INVESTMENTS_NAME
    from apps.modules.budgets.registry import MODULE_KEY as BUDGETS_KEY, display_name as BUDGETS_NAME

    return [
        {"module_key": REQUESTS_KEY, "display_name": REQUESTS_NAME},
        {"module_key": VENDORS_KEY, "display_name": VENDORS_NAME},
        {"module_key": CASHIER_KEY, "display_name": CASHIER_NAME},
        {"module_key": BANK_EXPENSES_KEY, "display_name": BANK_EXPENSES_NAME},
        {"module_key": CORPORATE_CARD_KEY, "display_name": CORPORATE_CARD_NAME},
        {"module_key": NOTES_KEY, "display_name": NOTES_NAME},
        {"module_key": N8N_KEY, "display_name": N8N_NAME},
        {"module_key": TG_APPROVALS_KEY, "display_name": TG_APPROVALS_NAME},
        {"module_key": PAYROLL_KEY, "display_name": PAYROLL_NAME},
        {"module_key": WALLETS_KEY, "display_name": WALLETS_NAME},
        {"module_key": REPORTS_KEY, "display_name": REPORTS_NAME},
        {"module_key": CLIENTS_DEBT_KEY, "display_name": CLIENTS_DEBT_NAME},
        {"module_key": INVESTMENTS_KEY, "display_name": INVESTMENTS_NAME},
        {"module_key": BUDGETS_KEY, "display_name": BUDGETS_NAME},
    ]

