from django.apps import AppConfig
import sys


class RequestsModuleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.requests"

    def ready(self):
        # Do not start background poller for management commands.
        if len(sys.argv) > 1 and sys.argv[1] in {
            "migrate",
            "makemigrations",
            "collectstatic",
            "shell",
            "test",
            "createsuperuser",
        }:
            return
        # Best-effort background poller for monthly auto-requests.
        from apps.modules.requests.auto_requests import start_auto_requests_poller

        start_auto_requests_poller()

