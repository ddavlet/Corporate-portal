from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.modules.ai_assistant.models import ChainNode, PendingConfirmation, UsageRecord
from apps.modules.ai_assistant.purge import purge_expired_chains
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.tenants.models import Tenant

CHAT = "-100500"
User = get_user_model()


class PurgeTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.now = timezone.now()
        self.old = self.now - timedelta(days=8)
        self.fresh = self.now - timedelta(days=1)

    def _node(self, mid, parent, created_at, chat=CHAT):
        return ChainNode.objects.create(
            tenant=self.tenant, chat_id=chat, message_id=mid, parent_message_id=parent,
            kind=ChainNode.KIND_USER, text="t", created_at=created_at,
        )

    def _mids(self):
        return set(ChainNode.objects.values_list("message_id", flat=True))

    def test_single_dead_branch_deleted_entirely(self):
        self._node(1, None, self.old)
        self._node(2, 1, self.old)
        self._node(3, 2, self.old)
        nodes, pendings = purge_expired_chains(now=self.now)
        self.assertEqual((nodes, pendings), (3, 0))
        self.assertEqual(ChainNode.objects.count(), 0)

    def test_fork_with_live_branch_keeps_trunk_and_live_branch(self):
        self._node(1, None, self.old)  # A
        self._node(2, 1, self.old)  # B
        self._node(3, 2, self.old)  # C, dead leaf
        self._node(4, 2, self.fresh)  # D, live branch
        nodes, _ = purge_expired_chains(now=self.now)
        self.assertEqual(nodes, 1)
        self.assertEqual(self._mids(), {1, 2, 4})

    def test_all_fresh_untouched(self):
        self._node(1, None, self.fresh)
        self._node(2, 1, self.fresh)
        self.assertEqual(purge_expired_chains(now=self.now), (0, 0))
        self.assertEqual(self._mids(), {1, 2})

    def test_children_in_other_chat_do_not_protect_node(self):
        self._node(1, None, self.old, chat=CHAT)
        self._node(2, 1, self.fresh, chat="-100999")
        purge_expired_chains(now=self.now)
        self.assertFalse(ChainNode.objects.filter(chat_id=CHAT).exists())
        self.assertTrue(ChainNode.objects.filter(chat_id="-100999").exists())

    def test_old_pending_deleted_usage_records_kept(self):
        user = User.objects.create_user(username="boss", password="x", telegram_from_id=777)
        tg = TelegramMessage.objects.create(tenant=self.tenant, recipient_id=CHAT, message_id=300, sent_at=self.old)

        def pending(created_at, status):
            return PendingConfirmation.objects.create(
                tenant=self.tenant, chat_id=CHAT, requester_user=user, requester_tg_id=777,
                origin_message_id=100, confirmation_message=tg, agent_messages=[], tool_calls=[],
                status=status, created_at=created_at, expires_at=created_at + timedelta(hours=24),
            )

        old_pending = pending(self.old, PendingConfirmation.STATUS_PENDING)
        fresh_pending = pending(self.fresh, PendingConfirmation.STATUS_CONFIRMED)
        UsageRecord.objects.create(
            tenant=self.tenant, user=user, chat_id=CHAT, created_at=self.old, model="m",
            outcome=UsageRecord.OUTCOME_ANSWERED,
        )
        nodes, pendings = purge_expired_chains(now=self.now)
        self.assertEqual((nodes, pendings), (0, 1))
        self.assertFalse(PendingConfirmation.objects.filter(pk=old_pending.pk).exists())
        self.assertTrue(PendingConfirmation.objects.filter(pk=fresh_pending.pk).exists())
        self.assertEqual(UsageRecord.objects.count(), 1)
        self.assertTrue(TelegramMessage.objects.filter(pk=tg.pk).exists())
