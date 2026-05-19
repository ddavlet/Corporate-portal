from django.contrib import admin
from django.conf import settings
from django.urls import path, include

from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.views_otp import OtpRequestView, OtpVerifyView
from apps.accounts.views_password import ChangePasswordView
from apps.accounts.views_telegram_login_widget import TelegramLoginWidgetAuthView
from apps.accounts.views_telegram_oidc import TelegramOidcConfigView, TelegramOidcExchangeView
from apps.accounts.views_telegram_webapp import TelegramWebAppAuthView
from apps.modules.requests.views import FileGatewayView, FileDownloadView
from apps.modules.n8n_integration.views import AiChatProxyView, CashflowDataProxyView, PnlDataProxyView
from apps.mcp_server.oauth.views import McpLoginView
from apps.mcp_server.oauth.metadata_views import (
    AuthorizationServerMetadataView,
    ProtectedResourceMetadataView,
)
from apps.mcp_server.oauth.redirects import McpLoginLegacyRedirectView
from apps.tenants.views import (
    AccessMatrixView,
    ModuleCatalogView,
    SettingsAccessView,
    TenantMessagingWebhookView,
    TenantCashExpenseIdFormatView,
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
    path("api/auth/telegram/oidc/config/", TelegramOidcConfigView.as_view(), name="telegram_oidc_config"),
    path("api/auth/telegram/oidc/exchange/", TelegramOidcExchangeView.as_view(), name="telegram_oidc_exchange"),
    path("api/auth/telegram/login-widget/", TelegramLoginWidgetAuthView.as_view(), name="telegram_login_widget_auth"),
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
    path(
        "api/tenant/cash-expense-id-format/",
        TenantCashExpenseIdFormatView.as_view(),
        name="tenant_cash_expense_id_format",
    ),
    path("api/tenant-integration-config/", TenantIntegrationConfigView.as_view(), name="tenant_integration_config"),
    path("api/tenant-integration-config/messaging-webhook/", TenantMessagingWebhookView.as_view(), name="tenant_messaging_webhook"),
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
    path("api/contracts/", include("apps.modules.contracts.urls")),

    # Messaging gateway webhook
    path("api/messaging-gateway/", include("apps.modules.telegram_approvals.urls")),

    # MCP OAuth — discovery at host root (MCP spec), login outside /mcp/ (Django only)
    path(
        ".well-known/oauth-authorization-server",
        AuthorizationServerMetadataView.as_view(),
        name="mcp_oauth_authorization_server_metadata",
    ),
    path(
        ".well-known/oauth-protected-resource",
        ProtectedResourceMetadataView.as_view(),
        name="mcp_oauth_protected_resource_metadata",
    ),
    path("oauth/login/", McpLoginView.as_view(), name="mcp_oauth_login"),
    # Legacy URLs (ASGI also 301s these before FastMCP; kept for Django test client).
    path("mcp/oauth/login/", McpLoginLegacyRedirectView.as_view(), name="mcp_oauth_login_legacy_mcp_prefix"),
    path("oauth/mcp/login/", McpLoginLegacyRedirectView.as_view(), name="mcp_oauth_login_legacy_oauth_prefix"),
    path("mcp/login/", McpLoginLegacyRedirectView.as_view(), name="mcp_oauth_login_legacy"),
]

for _n8n_seg in settings.N8N_INTEGRATION_MOUNT_PATHS:
    urlpatterns.append(
        path(f"api/{_n8n_seg}/", include("apps.modules.n8n_integration.urls")),
    )

