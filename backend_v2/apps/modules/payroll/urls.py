from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.payroll.views import PayrollDocumentCreateView, PayrollDocumentViewSet

router = DefaultRouter()
router.register(r"documents", PayrollDocumentViewSet, basename="payroll-documents")

urlpatterns = [
    path("documents/create/", PayrollDocumentCreateView.as_view(), name="payroll-documents-create"),
    path("", include(router.urls)),
]
