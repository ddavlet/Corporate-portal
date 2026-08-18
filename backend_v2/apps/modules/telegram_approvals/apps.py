from django.apps import AppConfig


class TelegramApprovalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.telegram_approvals"
    label = "telegram_approvals"
    verbose_name = "Messaging Gateway"

    def ready(self):
        from apps.modules.telegram_approvals import checks  # noqa: F401

