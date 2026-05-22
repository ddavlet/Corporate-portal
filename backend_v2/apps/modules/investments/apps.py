import sys

from django.apps import AppConfig


class InvestmentsModuleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.investments"

    def ready(self):
        if len(sys.argv) > 1 and sys.argv[1] in {
            "migrate",
            "makemigrations",
            "collectstatic",
            "shell",
            "test",
            "createsuperuser",
        }:
            return
        from apps.modules.investments.notification_services import start_invest_notification_poller

        start_invest_notification_poller()
