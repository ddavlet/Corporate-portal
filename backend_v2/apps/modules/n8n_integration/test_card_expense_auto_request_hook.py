import datetime as dt
from decimal import Decimal
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.corporate_card.models import CardExpense, CardExpenseAutoRequestConfig
from apps.modules.n8n_integration.event_handlers import notify_request_payed
from apps.modules.n8n_integration.views import _created_card_expense_ids
from apps.modules.requests import card_expense_auto_requests, payment_step_guards, status_events
from apps.modules.requests.models import Request
from apps.modules.requests.tests_card_expense_auto_requests import enable_card_auto_requests_for
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import Tenant, TenantModuleConfig

User = get_user_model()

TASHKENT = dt.timezone(dt.timedelta(hours=5))


@override_settings(
    BASE_DOMAIN="example.com",
    N8N_INTEGRATION_TOKEN="integ-test-secret",
    ALLOWED_HOSTS=["acme.example.com", "testserver"],
)
class N8nCardExpenseAutoRequestHookTests(APITestCase):
    def setUp(self):
        self.system, _ = User.objects.update_or_create(pk=1, defaults={"username": "n8n_system"})
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        enable_card_auto_requests_for(self.tenant, updated_by=self.system)
        self.config = CardExpenseAutoRequestConfig.objects.create(
            tenant=self.tenant, wallet=self.wallet, is_enabled=True, payment_purpose="Реклама"
        )
        prefix = settings.N8N_INTEGRATION_URL_PREFIX.rstrip("/")
        self.url = f"{prefix}/corporate-card/expenses/"
        self.batch_url = f"{prefix}/corporate-card/expenses/batch/"

        self._saved_payed = status_events.REQUEST_PAYED_EVENT_HANDLERS
        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        self.payed_handler = Mock()
        status_events.REQUEST_PAYED_EVENT_HANDLERS = (self.payed_handler,)
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = ()

    def tearDown(self):
        status_events.REQUEST_PAYED_EVENT_HANDLERS = self._saved_payed
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = self._saved_suppressors

    def _headers(self):
        return {"HTTP_HOST": "acme.example.com", "HTTP_X_N8N_INTEGRATION_TOKEN": "integ-test-secret"}

    def _body(self, external_id, amount="150000.00"):
        return {
            "external_id": external_id,
            "title": "META *ADS",
            "amount": amount,
            "currency": "UZS",
            "expense_at": "2026-07-31T10:00:00+05:00",
        }

    def _post(self, body):
        # The hook runs on transaction commit; TestCase never commits, so run the callbacks here.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, body, format="json", **self._headers())

    def _post_batch(self, items):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.batch_url, items, format="json", **self._headers())

    def _card_requests(self):
        return Request.all_objects.filter(tenant=self.tenant, payment_type=Request.PAYMENT_TYPE_CARD)

    def _approved_request(self, amount="150000.00"):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.system,
            requester=self.system,
            title="t",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD,
            status=Request.STATUS_APPROVED,
            billing_date=dt.date(2026, 7, 1),
            created_at=dt.datetime(2026, 7, 25, 12, 0, tzinfo=TASHKENT),
        )

    def test_single_upsert_creates_one_request_and_repeat_does_not_duplicate(self):
        r1 = self._post(self._body("CARD-1"))
        self.assertEqual(r1.status_code, 201, r1.content)
        expense = CardExpense.objects.get(tenant=self.tenant, external_id="CARD-1")
        req = self._card_requests().get()
        self.assertEqual(req.expense_ref_id, expense.pk)
        self.assertEqual(req.status, Request.STATUS_PAYED)

        r2 = self._post(self._body("CARD-1"))

        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(self._card_requests().count(), 1)

    def test_batch_of_two_creates_two_requests(self):
        response = self._post_batch([self._body("CARD-1"), self._body("CARD-2", amount="200.00")])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self._card_requests().count(), 2)

    def test_batch_with_existing_expense_does_not_duplicate(self):
        self.assertEqual(self._post(self._body("CARD-1")).status_code, 201)

        response = self._post_batch([self._body("CARD-1"), self._body("CARD-2", amount="200.00")])

        self.assertEqual(response.status_code, 200, response.content)
        statuses = [row["status"] for row in response.json()["results"]]
        self.assertEqual(statuses, [200, 201])
        self.assertEqual(self._card_requests().count(), 2)

    def test_request_linked_by_reconciliation_gets_no_auto_request(self):
        existing = Request.objects.create(
            tenant=self.tenant,
            created_by=self.system,
            requester=self.system,
            title="t",
            amount=Decimal("150000.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_CARD,
            status=Request.STATUS_PAYED,
            payed_at=20260731,
            billing_date=dt.date(2026, 7, 1),
        )

        response = self._post(self._body("CARD-1"))

        self.assertEqual(response.status_code, 201, response.content)
        existing.refresh_from_db()
        expense = CardExpense.objects.get(tenant=self.tenant, external_id="CARD-1")
        self.assertEqual(existing.expense_ref_id, expense.pk)
        self.assertEqual(self._card_requests().count(), 1)

    def test_single_upsert_closes_approved_request_and_fires_payed_event(self):
        self.assertIn(notify_request_payed, self._saved_payed)
        approved = self._approved_request()

        response = self._post(self._body("CARD-1"))

        self.assertEqual(response.status_code, 201, response.content)
        approved.refresh_from_db()
        expense = CardExpense.objects.get(tenant=self.tenant, external_id="CARD-1")
        self.assertEqual(approved.status, Request.STATUS_PAYED)
        self.assertEqual(approved.expense_ref_id, expense.pk)
        self.assertEqual(self._card_requests().count(), 1)
        self.payed_handler.assert_called_once()
        self.assertEqual(self.payed_handler.call_args.kwargs["request_obj"].pk, approved.pk)

    def test_batch_two_same_amount_expenses_one_approved_request(self):
        approved = self._approved_request(amount="599250.00")

        response = self._post_batch([self._body("CARD-1", amount="599250.00"), self._body("CARD-2", amount="599250.00")])

        self.assertEqual(response.status_code, 200, response.content)
        results = response.json()["results"]
        expense_ids = sorted(CardExpense.objects.filter(tenant=self.tenant).values_list("id", flat=True))
        self.assertEqual(sorted(row["data"]["id"] for row in results), expense_ids)
        self.assertEqual(sorted(_created_card_expense_ids(results)), expense_ids)
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_PAYED)
        self.assertIn(approved.expense_ref_id, expense_ids)
        self.assertEqual(self._card_requests().count(), 2)
        self.assertEqual(
            sorted(self._card_requests().values_list("expense_ref_id", flat=True)),
            expense_ids,
        )

    def test_created_card_expense_ids_takes_only_201_rows(self):
        results = [
            {"index": 0, "status": 201, "data": {"id": 5}},
            {"index": 1, "status": 200, "data": {"id": 6}},
            {"index": 2, "status": 201, "data": {"id": "7"}},
            {"index": 3, "status": 201, "data": {}},
            {"index": 4, "status": 201, "data": None},
            "garbage",
        ]
        self.assertEqual(_created_card_expense_ids(results), [5, 7])

    def test_service_exception_does_not_change_response(self):
        with patch.object(
            card_expense_auto_requests, "process_card_expense_auto_request", side_effect=RuntimeError("boom")
        ):
            with self.assertLogs("apps.modules.requests.card_expense_auto_requests", level="ERROR"):
                response = self._post(self._body("CARD-1"))

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["external_id"], "CARD-1")
        self.assertTrue(CardExpense.objects.filter(tenant=self.tenant, external_id="CARD-1").exists())
        self.assertEqual(self._card_requests().count(), 0)

    def test_disabled_config_creates_no_requests(self):
        self.config.is_enabled = False
        self.config.save(update_fields=["is_enabled"])

        self.assertEqual(self._post(self._body("CARD-1")).status_code, 201)
        self.assertEqual(self._post_batch([self._body("CARD-2", amount="200.00")]).status_code, 200)

        self.assertEqual(self._card_requests().count(), 0)

    def test_disabled_corporate_card_module_creates_no_requests(self):
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="corporate_card").update(is_enabled=False)

        self.assertEqual(self._post(self._body("CARD-1")).status_code, 201)
        self.assertEqual(self._post_batch([self._body("CARD-2", amount="200.00")]).status_code, 200)

        self.assertEqual(self._card_requests().count(), 0)

    def test_batch_inside_outer_transaction_runs_hook_only_after_commit(self):
        # The Kapitalbank import posts the batch inside its own atomic block.
        approved = self._approved_request()
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                response = self.client.post(
                    self.batch_url, [self._body("CARD-1")], format="json", **self._headers()
                )
                self.assertEqual(response.status_code, 200, response.content)
                approved.refresh_from_db()
                self.assertEqual(approved.status, Request.STATUS_APPROVED)
                self.payed_handler.assert_not_called()

        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_PAYED)
        self.payed_handler.assert_called_once()

    def test_rolled_back_outer_transaction_creates_and_closes_nothing(self):
        approved = self._approved_request()
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                response = self.client.post(
                    self.batch_url,
                    [self._body("CARD-1"), self._body("CARD-2", amount="200.00")],
                    format="json",
                    **self._headers(),
                )
                self.assertEqual(response.status_code, 200, response.content)
                transaction.set_rollback(True)

        self.assertEqual(callbacks, [])
        approved.refresh_from_db()
        self.assertEqual(approved.status, Request.STATUS_APPROVED)
        self.assertEqual(self._card_requests().count(), 1)
        self.payed_handler.assert_not_called()
