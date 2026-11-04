from django.apps import AppConfig


class KapitalbankConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.kapitalbank"
    label = "kapitalbank"
    verbose_name = "Капиталбанк: загрузка выписки"
