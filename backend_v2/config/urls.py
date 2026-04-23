from django.contrib import admin
from django.conf import settings
from django.urls import path, include

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views_otp import OtpRequestView, OtpVerifyView
from apps.accounts.views_password import ChangePasswordView
from apps.accounts.views_telegram_webapp import TelegramWebAppAuthView
from apps.modules.requests.views import FileGatewayView, FileDownloadView
from apps.modules.n8n_integration.views import AiChatProxyView, CashflowDataProxyView, PnlDataProxyView
from apps.tenants.views import (
    AccessMatrixView,
    ModuleCatalogView,
    SettingsAccessView,
    TenantIntegrationConfigView,
    TenantModuleConfigView,
    UserPreferencesView,
)


urlpatterns = [
    path("api/admin/", admin.site.urls),

    # JWT auth for React
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/auth/otp/request/", OtpRequestView.as_view(), name="otp_request"),
    path("api/auth/otp/verify/", OtpVerifyView.as_view(), name="otp_verify"),
    path("api/auth/telegram/webapp/", TelegramWebAppAuthView.as_view(), name="telegram_webapp_auth"),
    path("api/auth/password/change/", ChangePasswordView.as_view(), name="password_change"),
    path("api/files/gateway/", FileGatewayView.as_view(), name="files_gateway"),
    path("api/files/download/", FileDownloadView.as_view(), name="files_download"),
    path("api/pnl-data/", PnlDataProxyView.as_view(), name="api_pnl_data"),
    path("api/cashflow-data/", CashflowDataProxyView.as_view(), name="api_cashflow_data"),
    path("api/ai-questions/chat/", AiChatProxyView.as_view(), name="api_ai_questions_chat"),
    path("api/reports/", include("apps.modules.reports.urls")),

    # Tenants + module config/permissions
    path("api/modules/", ModuleCatalogView.as_view(), name="module_catalog"),
    path("api/tenant-module-config/", TenantModuleConfigView.as_view(), name="tenant_module_config"),
    path("api/tenant-integration-config/", TenantIntegrationConfigView.as_view(), name="tenant_integration_config"),
    path("api/access-matrix/", AccessMatrixView.as_view(), name="admin_access_matrix"),
    path("api/settings-access/", SettingsAccessView.as_view(), name="settings_access"),
    path("api/user-preferences/", UserPreferencesView.as_view(), name="user_preferences_bulk"),
    path("api/user-preferences/<str:key>/", UserPreferencesView.as_view(), name="user_preference_upsert"),

    # Requests module (first module to scaffold)
    path("api/requests/", include("apps.modules.requests.urls")),

    path("api/vendors/", include("apps.modules.vendors.urls")),

    # Cash module
    path("api/cash/", include("apps.modules.cashier.urls")),

    # Bank module
    path("api/bank/", include("apps.modules.bank_expenses.urls")),

    # Corporate card module
    path("api/corporate-card/", include("apps.modules.corporate_card.urls")),

    # Notes module
    path("api/notes/", include("apps.modules.notes.urls")),

    path("api/feedback/", include("apps.modules.feedback.urls")),

    # Payroll accruals module
    path("api/payroll/", include("apps.modules.payroll.urls")),

    path("api/clients-debt/", include("apps.modules.clients_debt.urls")),

    path("api/wallets/", include("apps.modules.wallets.urls")),

    path("api/investments/", include("apps.modules.investments.urls")),

    path("api/budgets/", include("apps.modules.budgets.urls")),

    # Telegram approvals bridge webhook
    path("api/telegram-approvals/", include("apps.modules.telegram_approvals.urls")),
]

for _n8n_seg in settings.N8N_INTEGRATION_MOUNT_PATHS:
    urlpatterns.append(
        path(f"api/{_n8n_seg}/", include("apps.modules.n8n_integration.urls")),
    )

