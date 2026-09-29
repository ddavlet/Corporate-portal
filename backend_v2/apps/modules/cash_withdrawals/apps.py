from django.apps import AppConfig


class CashWithdrawalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.cash_withdrawals"
    label = "cash_withdrawals"
    verbose_name = "Снятие наличных"

    def ready(self):
        from apps.modules.cash_withdrawals.services import on_request_payed
        from apps.modules.requests import status_events

        status_events.register_request_payed_event_handler(on_request_payed)
