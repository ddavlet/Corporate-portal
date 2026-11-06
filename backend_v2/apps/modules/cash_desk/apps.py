from django.apps import AppConfig


class CashDeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.cash_desk"
    label = "cash_desk"
    verbose_name = "Касса"

    def ready(self):
        from apps.modules.cash_desk.services import on_request_payed
        from apps.modules.requests import status_events

        status_events.register_request_payed_event_handler(on_request_payed)
