from django.urls import path

from apps.modules.notes.views import NoteRecipientsView, NotesCreateView


urlpatterns = [
    path("", NotesCreateView.as_view(), name="notes-create"),
    path("recipients/", NoteRecipientsView.as_view(), name="notes-recipients"),
]
