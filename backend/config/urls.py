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

    # portal pages (на subdomain.kolberg.uz)
    path("web/requests", portal.requests_page),
    path("web/vendors", portal.vendors_page),
    path("web/requests-data", portal.requests_data),
    path("web/vendors-data", portal.vendors_data),
    path("web/vendor-request-data", portal.vendor_request_data),
]
