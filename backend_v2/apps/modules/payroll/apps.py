from django.apps import AppConfig


class PayrollModuleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.payroll"
    verbose_name = "Начисления ЗП"

    def ready(self):
        from apps.modules.payroll import hooks
        from apps.modules.requests import payment_step_guards, status_events

        status_events.register_request_rejected_event_handler(hooks.revert_document_to_draft_on_reject)
        payment_step_guards.register_payment_step_suppressor(hooks.suppress_payment_step_for_portal_payouts)
