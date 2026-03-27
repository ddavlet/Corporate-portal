from django.contrib import admin
from django.urls import path, include

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.tenants.views import ModuleCatalogView, TenantModuleConfigView


urlpatterns = [
    path("api/admin/", admin.site.urls),

    # JWT auth for React
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

    # Tenants + module config/permissions
    path("api/modules/", ModuleCatalogView.as_view(), name="module_catalog"),
    path("api/tenant-module-config/", TenantModuleConfigView.as_view(), name="tenant_module_config"),

    # Requests module (first module to scaffold)
    path("api/requests/", include("apps.modules.requests.urls")),

    # Cash module
    path("api/cash/", include("apps.modules.cashier.urls")),

    # Bank module
    path("api/bank/", include("apps.modules.bank_expenses.urls")),
]

