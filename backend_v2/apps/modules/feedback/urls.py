from django.urls import path

from apps.modules.feedback.views import (
    FeedbackAiRefineView,
    FeedbackSubmitView,
    MyFeedbackListView,
)

urlpatterns = [
    path("ai-refine/", FeedbackAiRefineView.as_view(), name="feedback-ai-refine"),
    path("submissions/", FeedbackSubmitView.as_view(), name="feedback-submissions"),
    path("my/", MyFeedbackListView.as_view(), name="feedback-my"),
]
