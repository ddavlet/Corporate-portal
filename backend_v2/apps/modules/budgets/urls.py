from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.budgets.views import BudgetViewSet

router = DefaultRouter()
router.register(r"", BudgetViewSet, basename="budgets")

urlpatterns = [
    path("", include(router.urls)),
]
