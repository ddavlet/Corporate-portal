from django.apps import AppConfig


class N8NIntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.n8n_integration"
    label = "n8n_integration"
    verbose_name = "Связь с n8n"
    request_payed_event_handlers = (
        "apps.modules.n8n_integration.event_handlers.notify_request_payed",
    )
    cash_withdrawal_received_event_handlers = (
        "apps.modules.n8n_integration.event_handlers.notify_cash_withdrawal_received",
    )

    def ready(self):
        from django.utils.module_loading import import_string

        from apps.modules.requests import status_events

        for handler_ref in self.request_payed_event_handlers:
            status_events.register_request_payed_event_handler(import_string(handler_ref))

        from apps.modules.cash_withdrawals import events as cash_withdrawal_events

        for handler_ref in self.cash_withdrawal_received_event_handlers:
            cash_withdrawal_events.register_receipt_confirmed_handler(import_string(handler_ref))
