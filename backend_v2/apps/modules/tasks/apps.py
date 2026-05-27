import sys

from django.apps import AppConfig

_SKIP_COMMANDS = frozenset({
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
})


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.tasks"

    def ready(self):
        if len(sys.argv) > 1 and sys.argv[1] in _SKIP_COMMANDS:
            return
        import apps.modules.tasks.triggers.autodiscover  # noqa: F401
