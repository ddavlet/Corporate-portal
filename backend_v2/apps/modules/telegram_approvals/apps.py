from django.apps import AppConfig


class TelegramApprovalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.telegram_approvals"
    label = "telegram_approvals"
    verbose_name = "Messaging Gateway"

