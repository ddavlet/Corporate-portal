from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.modules.requests import payment_step_guards
from apps.modules.requests.models import Approval, Request
from apps.modules.requests.services import list_request_action_items
from apps.tenants.models import Tenant

User = get_user_model()


def _suppress_all(*, request_obj):
    return "blocked for test"


class ListRequestActionItemsTests(TestCase):
    """Active-step rule must stay in sync with adapters.ts toPendingApprovals."""

    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-ai", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Other", subdomain="other-ai", is_active=True)
        self.user = User.objects.create_user(username="ai-approver", password="x")
        self.other_user = User.objects.create_user(username="ai-other", password="x")
        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = ()

    def tearDown(self):
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = self._saved_suppressors

    def _request(self, *, status, tenant=None, title="Закупка", amount="1500.50"):
        return Request.all_objects.create(
            tenant=tenant or self.tenant,
            created_by=self.user,
            requester=self.user,
            title=title,
            amount=Decimal(amount),
            currency=Request.CURRENCY_UZS,
            payment_type=Request.PAYMENT_TYPE_CASH,
            status=status,
            billing_date=timezone.localdate(),
        )

    def _approval(self, request_obj, *, step, step_type=Approval.STEP_TYPE_SERIAL, user=None, decision=None):
        return Approval.objects.create(
            request=request_obj,
            approver_user=user or self.user,
            step=step,
            step_type=step_type,
            decision=decision or Approval.DECISION_PENDING,
        )

    def _items(self, user=None, tenant=None):
        return list_request_action_items(tenant=tenant or self.tenant, user=user or self.user)

    # p.6
    def test_pending_serial_step_matching_status_is_listed(self):
        req = self._request(status=Request.STATUS_PROGRESS_2)
        self._approval(req, step=1, decision=Approval.DECISION_APPROVED)
        approval = self._approval(req, step=2)

        items = self._items()

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["kind"], "request")
        self.assertEqual(item["id"], req.id)
        self.assertEqual(item["approval_id"], approval.id)
        self.assertEqual(item["step"], 2)
        self.assertEqual(item["step_type"], Approval.STEP_TYPE_SERIAL)
        self.assertEqual(item["title"], "Закупка")
        self.assertEqual(item["amount"], Decimal("1500.50"))
        self.assertEqual(item["currency"], Request.CURRENCY_UZS)
        self.assertEqual(item["type_code"], Request.PAYMENT_TYPE_CASH)
        self.assertEqual(item["type_label"], Request.PAYMENT_TYPE_CASH)
        self.assertEqual(item["created_at"], req.created_at)
        self.assertEqual(item["link"], f"/requests/{req.id}")

    def test_empty_title_falls_back_to_request_number(self):
        req = self._request(status=Request.STATUS_PROGRESS_1, title="")
        self._approval(req, step=1)

        self.assertEqual(self._items()[0]["title"], f"Заявка #{req.id}")

    # p.7
    def test_future_step_is_not_listed(self):
        req = self._request(status=Request.STATUS_PROGRESS_2)
        self._approval(req, step=2, user=self.other_user)
        self._approval(req, step=3)

        self.assertEqual(self._items(), [])

    # p.8
    def test_payment_step_listed_when_approved_and_gone_after_payed(self):
        req = self._request(status=Request.STATUS_APPROVED)
        self._approval(req, step=1, decision=Approval.DECISION_APPROVED)
        payment = self._approval(req, step=2, step_type=Approval.STEP_TYPE_PAYMENT)

        items = self._items()
        self.assertEqual([i["approval_id"] for i in items], [payment.id])
        self.assertEqual(items[0]["step_type"], Approval.STEP_TYPE_PAYMENT)

        req.status = Request.STATUS_PAYED
        req.save(update_fields=["status"])
        self.assertEqual(self._items(), [])

    def test_payment_step_not_listed_before_approval(self):
        req = self._request(status=Request.STATUS_PROGRESS_1)
        self._approval(req, step=1, user=self.other_user)
        self._approval(req, step=2, step_type=Approval.STEP_TYPE_PAYMENT)

        self.assertEqual(self._items(), [])

    def test_suppressed_payment_step_is_not_listed(self):
        payment_step_guards.register_payment_step_suppressor(_suppress_all)
        req = self._request(status=Request.STATUS_APPROVED)
        self._approval(req, step=2, step_type=Approval.STEP_TYPE_PAYMENT)
        serial_req = self._request(status=Request.STATUS_PROGRESS_1)
        self._approval(serial_req, step=1)

        self.assertEqual([i["id"] for i in self._items()], [serial_req.id])

    # p.9
    def test_notification_step_is_not_listed(self):
        req = self._request(status=Request.STATUS_PROGRESS_1)
        self._approval(req, step=1, step_type=Approval.STEP_TYPE_NOTIFICATION)

        self.assertEqual(self._items(), [])

    def test_vacation_step_turned_into_notification_is_not_listed(self):
        # start_vacation flips the approver's serial steps to notification; rows created
        # while on vacation carry step_type=notification and need no action.
        req = self._request(status=Request.STATUS_PROGRESS_1)
        self._approval(req, step=1, step_type=Approval.STEP_TYPE_NOTIFICATION)
        self._approval(req, step=1, user=self.other_user)

        self.assertEqual(self._items(), [])
        self.assertEqual([i["id"] for i in self._items(user=self.other_user)], [req.id])

    # p.10
    def test_rejected_and_deleted_requests_are_not_listed(self):
        for status in (Request.STATUS_REJECTED, Request.STATUS_DELETED):
            req = self._request(status=status)
            self._approval(req, step=1)
            self._approval(req, step=2, step_type=Approval.STEP_TYPE_PAYMENT)

        self.assertEqual(self._items(), [])

    def test_decided_rows_are_not_listed(self):
        for decision in (Approval.DECISION_APPROVED, Approval.DECISION_REJECTED, Approval.DECISION_CANCELED):
            req = self._request(status=Request.STATUS_PROGRESS_1)
            self._approval(req, step=1, decision=decision)

        self.assertEqual(self._items(), [])

    # p.12
    def test_other_tenant_and_other_user_rows_are_not_listed(self):
        foreign = self._request(status=Request.STATUS_PROGRESS_1, tenant=self.other_tenant)
        self._approval(foreign, step=1)
        not_mine = self._request(status=Request.STATUS_PROGRESS_1)
        self._approval(not_mine, step=1, user=self.other_user)

        self.assertEqual(self._items(), [])
        self.assertEqual([i["id"] for i in self._items(tenant=self.other_tenant)], [foreign.id])

    def test_one_item_per_request(self):
        # Same user on a serial step and the payment step that shares the step number.
        req = self._request(status=Request.STATUS_PROGRESS_2)
        first = self._approval(req, step=2)
        self._approval(req, step=2, step_type=Approval.STEP_TYPE_PAYMENT)

        items = self._items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["approval_id"], first.id)

    def test_query_count_does_not_grow_with_requests(self):
        for _ in range(5):
            req = self._request(status=Request.STATUS_PROGRESS_1)
            self._approval(req, step=1)

        with CaptureQueriesContext(connection) as ctx:
            items = self._items()

        self.assertEqual(len(items), 5)
        self.assertEqual(len(ctx.captured_queries), 1)
