from django.contrib import admin
from django.urls import path
from apps.portal import views as portal

urlpatterns = [
    path("admin/", admin.site.urls),

    # login (на login.kolberg.uz)
    path("login/", portal.login_view),
    path("logout/", portal.logout_view),
    path("choose-tenant/", portal.choose_tenant_view),

    # portal pages (на subdomain.kolberg.uz)
    path("web/requests", portal.requests_page),
    path("web/vendors", portal.vendors_page),
    path("web/requests-data", portal.requests_data),
    path("web/vendors-data", portal.vendors_data),
    path("web/vendor-request-data", portal.vendor_request_data),
]
