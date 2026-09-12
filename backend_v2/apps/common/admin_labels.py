from django.contrib import admin


def set_portal_labels(model, singular: str, plural: str) -> None:
    """Set admin-facing names without touching model Meta / migrations."""
    model._meta.verbose_name = singular
    model._meta.verbose_name_plural = plural


def register_portal(model, singular: str, plural: str, admin_class=None, **options):
    set_portal_labels(model, singular, plural)
    if model in admin.site._registry:
        return
    if admin_class is not None:
        admin.site.register(model, admin_class)
        return
    admin.site.register(model, type(f"{model.__name__}Admin", (admin.ModelAdmin,), options))
