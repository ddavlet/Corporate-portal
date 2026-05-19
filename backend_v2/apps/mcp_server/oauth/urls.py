from django.urls import path
from .views import McpLoginView

urlpatterns = [
    path("login/", McpLoginView.as_view(), name="mcp_oauth_login"),
]
