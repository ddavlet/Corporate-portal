from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.modules.tasks.views import TaskViewSet

router = DefaultRouter()
router.register(r"", TaskViewSet, basename="tasks")

urlpatterns = [
    path("", include(router.urls)),
]
