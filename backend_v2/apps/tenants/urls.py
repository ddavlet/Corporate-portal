from django.urls import path

from apps.tenants.views import ModuleCatalogView, TenantModuleConfigView


urlpatterns = [
    path("", ModuleCatalogView.as_view(), name="module_catalog"),
    path("config/", TenantModuleConfigView.as_view(), name="tenant_module_config"),
]

