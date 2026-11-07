from django.apps import AppConfig


class DividendPayoutsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.dividend_payouts"
    label = "dividend_payouts"
    verbose_name = "Дивиденды: правила выплат"

    def ready(self):
        from apps.modules.dividend_payouts.services import on_request_payed
        from apps.modules.requests import status_events

        status_events.register_request_payed_event_handler(on_request_payed)
