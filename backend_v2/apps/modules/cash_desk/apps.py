from django.apps import AppConfig


class CashDeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.cash_desk"
    label = "cash_desk"
    verbose_name = "Касса"

    def ready(self):
        # Payed-event handler is registered in a later step.
        pass
