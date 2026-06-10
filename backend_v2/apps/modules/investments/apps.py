import os
import sys

from django.apps import AppConfig

# Management commands that should NOT trigger background pollers: one-shots, dev helpers,
# and anything that should exit immediately rather than start daemon threads.
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
    "run_invest_notifications",
})


class InvestmentsModuleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.investments"

    def ready(self):
        # Always connect signals (cheap, no side effects).
        from apps.modules.investments import signals  # noqa: F401

        # Skip for management commands that shouldn't spawn daemon threads.
        if len(sys.argv) > 1 and sys.argv[1] in _NO_POLLER_COMMANDS:
            return
        # Opt-IN. Default deployment: `backend_cron` container (see backend_v2/cron/crontab).
        # Set INVEST_NOTIFY_POLLER=1 to enable the legacy
        # in-process daemon thread (useful for local dev; in production with N gunicorn
        # workers it spawns N threads, which is what the management command exists to avoid).
        if os.environ.get("INVEST_NOTIFY_POLLER", "0") != "1":
            return
        from apps.modules.investments.notification_services import start_invest_notification_poller

        start_invest_notification_poller()
