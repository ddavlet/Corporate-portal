from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.payroll.views import PayrollDocumentViewSet

router = DefaultRouter()
router.register(r"documents", PayrollDocumentViewSet, basename="payroll-documents")

urlpatterns = [
    path("", include(router.urls)),
]
