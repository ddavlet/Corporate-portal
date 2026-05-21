from django.apps import AppConfig


class N8NIntegrationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.n8n_integration"
    label = "n8n_integration"
    verbose_name = "n8n integration"

    def ready(self):
        from apps.modules.requests import status_events
        from apps.modules.n8n_integration import event_handlers
        status_events.REQUEST_PAYED_EVENT_HANDLERS = (
            *status_events.REQUEST_PAYED_EVENT_HANDLERS,
            event_handlers.notify_request_payed,
        )
