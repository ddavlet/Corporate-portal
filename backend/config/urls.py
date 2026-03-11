from django.contrib import admin
from django.urls import path
from apps.portal import views as portal
from apps.core import views as core

urlpatterns = [
    path("admin/", admin.site.urls),

    # core login (на login.kolberg.uz)
    path("login/", core.login_view),
    path("logout/", core.logout_view),
    path("choose-tenant/", core.choose_tenant_view),

    # password management
    path("password/change/", core.password_change),
    path("password/change/done/", core.password_change_done),
    path("web/reports/corporate-investments/", core.corporate_investments_report),

    # portal pages (на subdomain.kolberg.uz)
    path("web/", portal.tenant_home),
    path("web/requests/", portal.requests_page),
    path("web/vendors/", portal.vendors_page),
    path("web/requests-data/", portal.requests_data),
    path("web/vendors-data/", portal.vendors_data),
    path("web/vendor-request-data/", portal.vendor_request_data),
    path("web/reports/", portal.reports_page),
    path("web/reports/pnl/", portal.pnl_page),
    path("web/pnl-data/", portal.pnl_data),
    path("web/file", portal.get_file),
    path("web/reports/cashflow/", portal.cashflow_page),
    path("web/cashflow-data/", portal.cashflow_data),
    path("web/reports/investments/", portal.investments_page),
    path("web/investments-data/", portal.investments_data),
]
