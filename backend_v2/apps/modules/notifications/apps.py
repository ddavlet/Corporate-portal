from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.notifications"
    label = "notifications"
    verbose_name = "Уведомления"

    def ready(self):
        from apps.modules.investments import approval_events as investment_approval_events
        from apps.modules.notifications import signals  # also connects pre/post_delete receivers on Request
        from apps.modules.requests import approval_events as request_approval_events
        from apps.modules.requests import status_events

        request_approval_events.register_request_approvals_changed_handler(signals.on_approvals_changed)
        investment_approval_events.register_investment_approvals_changed_handler(signals.on_approvals_changed)
        status_events.register_request_payed_event_handler(signals.on_request_payed)
        status_events.register_request_rejected_event_handler(signals.on_request_rejected)
