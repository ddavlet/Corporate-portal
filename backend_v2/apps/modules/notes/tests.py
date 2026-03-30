from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.tenants.models import Tenant
from apps.modules.notes.models import Note


User = get_user_model()


class NotesSmokeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.sender = User.objects.create_user(username="sender", password="x")
        self.recipient = User.objects.create_user(username="recipient", password="x")

    def test_can_create_note(self):
        obj = Note.objects.create(
            tenant=self.tenant,
            created_by=self.sender,
            recipient_user=self.recipient,
            target_type=Note.TARGET_REQUEST,
            target_id=1,
            message="Hello",
        )
        self.assertIsNotNone(obj.id)
        self.assertEqual(Note.objects.filter(tenant=self.tenant).count(), 1)

