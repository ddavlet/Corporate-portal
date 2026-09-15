"""Tests for the delete_lemonaqua_unmatched_card_requests one-off command."""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.requests.models import Request, RequestComment
from apps.tenants.models import Tenant

User = get_user_model()


def _run(**options):
    out = StringIO()
    call_command("delete_lemonaqua_unmatched_card_requests", stdout=out, **options)
    return out.getvalue()


class DeleteLemonaquaUnmatchedCardRequestsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-deletetest", is_active=True)
        self.system_user = User.objects.create_user(id=1, username="app", full_name="Система", password="x")
        self.admin = User.objects.create_user(username="admin-delete", password="x")

        self.req_7940 = self._make_request(id=7940, amount="241000.00", payed_at=20260904)
        self.req_7980 = self._make_request(id=7980, amount="528000.00", payed_at=20260907)

    def _make_request(self, *, id, amount, payed_at):
        return Request.objects.create(
            id=id, tenant=self.tenant, created_by=self.admin, requester=self.admin,
            title="Lemonfit Aqua", description="", amount=Decimal(amount), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1), vendor="FITLINE", category="Содержание клуба",
            payment_purpose="Расходники", expense_id=None,
            status=Request.STATUS_PAYED, payed_at=payed_at,
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.req_7940.refresh_from_db()
        self.req_7980.refresh_from_db()
        self.assertEqual(self.req_7940.status, Request.STATUS_PAYED)
        self.assertEqual(self.req_7980.status, Request.STATUS_PAYED)
        self.assertIn("Would delete: 2", output)
        self.assertIn("Dry run complete", output)

    def test_apply_soft_deletes_both_requests(self):
        output = _run(apply=True)

        self.req_7940.refresh_from_db()
        self.req_7980.refresh_from_db()
        self.assertEqual(self.req_7940.status, Request.STATUS_DELETED)
        self.assertEqual(self.req_7980.status, Request.STATUS_DELETED)
        self.assertIn("Deleted: 2", output)

        # rows survive — this is a soft delete, not a real one
        self.assertTrue(Request.all_objects.filter(pk=7940).exists())
        self.assertTrue(Request.all_objects.filter(pk=7980).exists())
        # and drop out of the default (active) manager
        self.assertFalse(Request.objects.filter(pk=7940).exists())
        self.assertFalse(Request.objects.filter(pk=7980).exists())

        comment = RequestComment.objects.get(request_id=7940)
        self.assertEqual(comment.created_by_id, 1)
        self.assertIn("удалённая", comment.body)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Deleted: 0", output)
        self.assertIn("Already correct: 2", output)
        self.assertEqual(RequestComment.objects.count(), 2)

    def test_unexpected_state_is_skipped(self):
        Request.objects.filter(pk=7940).update(amount=Decimal("1.00"))

        output = _run(apply=True)

        self.req_7940.refresh_from_db()
        self.assertEqual(self.req_7940.status, Request.STATUS_PAYED)
        self.assertIn("Deleted: 1", output)
        self.assertIn("Skipped (1)", output)
        self.assertIn("unexpected state", output)

    def test_apply_without_system_user_still_deletes(self):
        User.objects.filter(pk=1).delete()

        output = _run(apply=True)

        self.req_7940.refresh_from_db()
        self.assertEqual(self.req_7940.status, Request.STATUS_DELETED)
        self.assertIn("Deleted: 2", output)
        self.assertEqual(RequestComment.objects.count(), 0)
