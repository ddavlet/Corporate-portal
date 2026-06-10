import os
import sys

from django.apps import AppConfig

# Management commands that should NOT trigger background pollers.
_NO_POLLER_COMMANDS = frozenset({
    "migrate",
    "makemigrations",
    "collectstatic",
    "shell",
    "dbshell",
    "test",
    "createsuperuser",
    "check",
    "showmigrations",
    "sqlmigrate",
    "dumpdata",
    "loaddata",
    "compilemessages",
    "makemessages",
    "diffsettings",
    "run_auto_requests",
    "purge_expired_draft_requests",
})


class RequestsModuleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.requests"

    def ready(self):
        # Skip for management commands that shouldn't spawn daemon threads.
        if len(sys.argv) > 1 and sys.argv[1] in _NO_POLLER_COMMANDS:
            return
        # Opt-IN. Default deployment: `backend_cron` container (see backend_v2/cron/crontab).
        # Set AUTO_REQUESTS_POLLER=1 to enable the legacy
        # in-process daemon thread (useful for local dev; in production with N gunicorn
        # workers it spawns N threads, which is what the management command exists to avoid).
        if os.environ.get("AUTO_REQUESTS_POLLER", "0") != "1":
            return
        from apps.modules.requests.auto_requests import start_auto_requests_poller

        start_auto_requests_poller()

