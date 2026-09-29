from django.apps import AppConfig


class CashWithdrawalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.cash_withdrawals"
    label = "cash_withdrawals"
    verbose_name = "Снятие наличных"
