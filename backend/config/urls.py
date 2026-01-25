from django.contrib import admin
from django.urls import path
from apps.portal import views as portal

urlpatterns = [
    path("admin/", admin.site.urls),

    # login (на login.kolberg.uz)
    path("login/", portal.login_view),
    path("logout/", portal.logout_view),
    path("choose-tenant/", portal.choose_tenant_view),

    # password management
    path("password/change/", auth_views.PasswordChangeView.as_view(
            template_name="auth/password_change.html",
            success_url="/password/change/done/",
        ),
        name="password_change",
    ),
    path("password/change/done/", auth_views.PasswordChangeDoneView.as_view(
            template_name="auth/password_change_done.html",
        ),
        name="password_change_done",
    ),

    # portal pages (на subdomain.kolberg.uz)
    path("web/requests", portal.requests_page),
    path("web/vendors", portal.vendors_page),
    path("web/requests-data", portal.requests_data),
    path("web/vendors-data", portal.vendors_data),
    path("web/vendor-request-data", portal.vendor_request_data),
]
