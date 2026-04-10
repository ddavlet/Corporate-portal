from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.clients_debt.views import ClientDebtSnapshotViewSet


router = DefaultRouter()
router.register(r"", ClientDebtSnapshotViewSet, basename="clients-debt")

urlpatterns = [
    path("", include(router.urls)),
]

