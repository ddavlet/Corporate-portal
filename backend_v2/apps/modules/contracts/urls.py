from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.contracts.views import ContractViewSet

router = DefaultRouter()
router.register(r"", ContractViewSet, basename="contracts")

urlpatterns = [
    path("", include(router.urls)),
]
