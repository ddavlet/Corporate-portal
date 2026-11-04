from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.modules.ai_assistant.models import ChainNode
from apps.modules.registry import list_modules
from apps.tenants.models import Tenant


class ChainNodeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)

    def test_chain_node_unique_per_tenant_chat_message(self):
        ChainNode.objects.create(tenant=self.tenant, chat_id="-100", message_id=1, kind=ChainNode.KIND_USER, text="a")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ChainNode.objects.create(
                    tenant=self.tenant, chat_id="-100", message_id=1, kind=ChainNode.KIND_MEMBER, text="b"
                )

    def test_same_message_id_in_other_chat_allowed(self):
        ChainNode.objects.create(tenant=self.tenant, chat_id="-100", message_id=1, kind=ChainNode.KIND_USER)
        ChainNode.objects.create(tenant=self.tenant, chat_id="-200", message_id=1, kind=ChainNode.KIND_USER)
        self.assertEqual(ChainNode.objects.count(), 2)


class RegistryTests(TestCase):
    def test_registry_lists_ai_assistant(self):
        self.assertIn("ai_assistant", [m["module_key"] for m in list_modules()])
