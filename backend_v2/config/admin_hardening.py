from django.contrib import admin


def disable_admin_deletions() -> None:
    """
    Disable object deletion via Django admin globally.

    Covers:
    - single-object delete pages/buttons;
    - bulk delete action (`delete_selected`);
    - inline formset row deletions.
    """
    if getattr(admin.ModelAdmin, "_kolberg_delete_disabled", False):
        return

    def _deny_delete_permission(self, request, obj=None):
        return False

    admin.ModelAdmin.has_delete_permission = _deny_delete_permission
    admin.InlineModelAdmin.has_delete_permission = _deny_delete_permission
    admin.ModelAdmin._kolberg_delete_disabled = True

    try:
        admin.site.disable_action("delete_selected")
    except KeyError:
        # Action may already be absent; keep startup idempotent.
        pass
