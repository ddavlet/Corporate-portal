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

    return [
        {"module_key": REQUESTS_KEY, "display_name": REQUESTS_NAME},
        {"module_key": VENDORS_KEY, "display_name": VENDORS_NAME},
        {"module_key": CASHIER_KEY, "display_name": CASHIER_NAME},
        {"module_key": BANK_EXPENSES_KEY, "display_name": BANK_EXPENSES_NAME},
        {"module_key": CORPORATE_CARD_KEY, "display_name": CORPORATE_CARD_NAME},
        {"module_key": NOTES_KEY, "display_name": NOTES_NAME},
    ]

