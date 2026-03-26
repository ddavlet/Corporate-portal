from django.urls import path

from apps.tenants.views import ModuleCatalogView, TenantModuleConfigView, UserModulePermissionsView


urlpatterns = [
    path("", ModuleCatalogView.as_view(), name="module_catalog"),
    path("config/", TenantModuleConfigView.as_view(), name="tenant_module_config"),
    path("permissions/", UserModulePermissionsView.as_view(), name="user_module_permissions"),
]

