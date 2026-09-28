"""Must match RequestPaymentPurposeConfig.category for salary purposes in tenant form config."""

SALARY_CATEGORY = "Зарплата/Аванс/Премия"

MODULE_KEY = "payroll"

KIND_LABELS = {
    "salary": "Зарплата",
    "advance": "Аванс",
    "bonus": "Премия",
}

PORTAL_PAYOUT_BLOCK_REASON = "Оплата выполняется через начисление ЗП в портале."

# pk of the service account shown as «Система» (see n8n_integration.views._system_user).
SYSTEM_USER_PK = 1
