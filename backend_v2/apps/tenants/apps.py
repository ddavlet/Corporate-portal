from django.apps import AppConfig


class TenantsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tenants"
    verbose_name = "Компания"

    def ready(self):
        from apps.tenants import checks  # noqa: F401  (registers system checks)
