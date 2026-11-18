import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.modules.corporate_card.models import CardExpense, CardExpenseAutoRequestConfig
from apps.modules.requests import card_expense_pending_request_close, payment_step_guards, status_events
from apps.modules.requests.approval_bootstrap import create_approval_rows_for_request
from apps.modules.requests.approval_workflow import _recalculate_request_status, confirm_approval_by_id
from apps.modules.requests.card_expense_auto_requests import (
    ACTION_CLOSED,
    ACTION_CREATED,
    ACTION_SKIPPED,
    process_card_expense_auto_request,
)
from apps.modules.requests.card_expense_pending_request_close import (
    pending_card_request_candidates,
    pending_request_close_comment,
)
from apps.modules.requests.models import (
    Approval,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalStepApproverConfig,
    RequestApprovalStepConfig,
    RequestComment,
)
from apps.modules.telegram_approvals.models import TelegramMessage
from apps.modules.telegram_approvals.services import TelegramDispatcher
from apps.modules.requests.tests_card_expense_auto_requests import enable_card_auto_requests_for
from apps.modules.wallets.resolution import get_or_create_corporate_wallet
from apps.tenants.models import Tenant, TenantMembership

User = get_user_model()

TASHKENT = dt.timezone(dt.timedelta(hours=5))
AMOUNT = Decimal("599250.00")
PURPOSE = "Реклама"


def _suppress_all(*, request_obj):
    return "payment step owned by another module"


class CardExpensePendingRequestCloseTests(TestCase):
    def setUp(self):
        self.system = User.objects.create_user(id=1, username="app", full_name="Система", password="x")
        self.tenant = Tenant.objects.create(name="Card", subdomain="cardclose", is_active=True)
        self.approver = User.objects.create_user(username="card-approver", password="x", telegram_chat_id=111)
        self.payer = User.objects.create_user(username="card-payer", password="x", telegram_chat_id=222)
        for user in (self.approver, self.payer):
            TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        self.wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        enable_card_auto_requests_for(self.tenant, updated_by=self.system)
        self.config = CardExpenseAutoRequestConfig.objects.create(
            tenant=self.tenant, wallet=self.wallet, is_enabled=True, payment_purpose=PURPOSE
        )

        cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=cfg, payment_type=Request.PAYMENT_TYPE_CARD, is_enabled=True
        )
        s1 = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt, step=1, is_enabled=True, step_type=Approval.STEP_TYPE_SERIAL
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=s1, approver_user=self.approver)
        self.payment_step = RequestApprovalStepConfig.objects.create(
            payment_type_config=pt, step=2, is_enabled=True, step_type=Approval.STEP_TYPE_PAYMENT
        )
        RequestApprovalStepApproverConfig.objects.create(step_config=self.payment_step, approver_user=self.payer)

        self.payed_calls = []
        self._saved_payed = status_events.REQUEST_PAYED_EVENT_HANDLERS
        self._saved_suppressors = payment_step_guards.PAYMENT_STEP_SUPPRESSORS
        status_events.REQUEST_PAYED_EVENT_HANDLERS = (self._count_payed,)
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = ()

        self.send_mock = self._patch_dispatcher("send")
        self.edit_mock = self._patch_dispatcher("edit")
        self.deactivate_mock = self._patch_dispatcher("deactivate")

    def tearDown(self):
        status_events.REQUEST_PAYED_EVENT_HANDLERS = self._saved_payed
        payment_step_guards.PAYMENT_STEP_SUPPRESSORS = self._saved_suppressors

    def _patch_dispatcher(self, name):
        patcher = patch.object(TelegramDispatcher, name, return_value=None)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _count_payed(self, *, request_obj):
        self.payed_calls.append(request_obj.pk)

    def _expense(self, *, amount=AMOUNT, currency="UZS", at=None, note="Оплата рекламы", wallet=None, tenant=None):
        return CardExpense.objects.create(
            tenant=tenant or self.tenant,
            wallet=wallet or self.wallet,
            title="Card payment",
            amount=amount,
            currency=currency,
            expense_at=at or dt.datetime(2026, 11, 10, 10, 0, tzinfo=TASHKENT),
            note=note,
            payload={},
            created_by=self.system,
        )

    def _request(self, *, status, amount=AMOUNT, currency="UZS", purpose="", created_at=None, **extra):
        fields = {
            "tenant": self.tenant,
            "created_by": self.approver,
            "requester": self.approver,
            "title": "t",
            "amount": amount,
            "currency": currency,
            "payment_type": Request.PAYMENT_TYPE_CARD,
            "payment_purpose": purpose,
            "status": status,
            "billing_date": dt.date(2026, 11, 1),
            "created_at": created_at or dt.datetime(2026, 11, 5, 12, 0, tzinfo=TASHKENT),
        }
        fields.update(extra)
        return Request.objects.create(**fields)

    def _approved_with_chain(self, **kwargs):
        req = self._request(status=Request.STATUS_DRAFT, **kwargs)
        create_approval_rows_for_request(req)
        _recalculate_request_status(req)
        step1 = Approval.objects.get(request=req, step=1)
        confirm_approval_by_id(tenant=self.tenant, approval_id=step1.id, approver_user_id=self.approver.id)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)
        return req

    def _candidate_ids(self, expense):
        return list(pending_card_request_candidates(expense=expense, preferred_purpose=PURPOSE).values_list("id", flat=True))

    def _tenant_requests(self):
        return Request.all_objects.filter(tenant=self.tenant)

    # 1
    def test_closes_approved_request_with_pending_payment_step(self):
        req = self._approved_with_chain()
        expense = self._expense(at=dt.datetime(2026, 11, 10, 23, 30, tzinfo=dt.timezone.utc))
        requests_before = self._tenant_requests().count()
        expenses_before = CardExpense.objects.count()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CLOSED)
        self.assertEqual(result.request_id, req.pk)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.expense_ref_id, expense.pk)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_CARD)
        self.assertEqual(req.expense_id, str(expense.pk))
        self.assertEqual(req.payed_at, 20261111)
        payment = Approval.objects.get(request=req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertEqual(payment.decision, Approval.DECISION_APPROVED)
        self.assertEqual(payment.comment, pending_request_close_comment(expense, config=self.config))
        comments = RequestComment.objects.filter(request=req, created_by=self.system)
        self.assertEqual(comments.count(), 1)
        self.assertIn(f"#{expense.pk} от 11.11.2026 на 599 250.00 UZS", comments.get().body)
        self.assertIn(
            f"Карта: «Основная», настройка автозаявок #{self.config.pk}.", comments.get().body
        )
        self.assertEqual(self.payed_calls, [req.pk])
        self.assertEqual(CardExpense.objects.count(), expenses_before)
        self.assertEqual(self._tenant_requests().count(), requests_before)

    # 2
    def test_payment_step_in_create_mode_does_not_create_card_expense(self):
        self.payment_step.payment_action_mode = RequestApprovalStepConfig.PAYMENT_ACTION_MODE_CREATE
        self.payment_step.save(update_fields=["payment_action_mode"])
        req = self._approved_with_chain()
        expense = self._expense()
        expenses_before = CardExpense.objects.count()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CLOSED)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(CardExpense.objects.count(), expenses_before)

    # 3
    def test_closes_approved_request_without_approvals(self):
        req = self._request(status=Request.STATUS_APPROVED)
        expense = self._expense()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CLOSED)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_PAYED)
        self.assertEqual(req.payed_at, 20261110)
        self.assertEqual(self.payed_calls, [req.pk])

    # 4
    def test_prefilled_expense_period_is_kept(self):
        req = self._request(status=Request.STATUS_APPROVED, expense_year=2026, expense_month=10, expense_day=15)
        expense = self._expense()

        process_card_expense_auto_request(expense.pk)

        req.refresh_from_db()
        self.assertEqual((req.expense_year, req.expense_month, req.expense_day), (2026, 10, 15))
        self.assertEqual(req.payed_at, 20261110)

    # 5
    def test_other_amount_or_currency_is_not_closed(self):
        other_amount = self._request(status=Request.STATUS_APPROVED, amount=Decimal("599251.00"))
        other_currency = self._request(status=Request.STATUS_APPROVED, currency="USD")
        expense = self._expense()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CREATED)
        for req in (other_amount, other_currency):
            req.refresh_from_db()
            self.assertEqual(req.status, Request.STATUS_APPROVED)
        self.assertEqual(self.payed_calls, [])

    # 6
    def test_non_approved_statuses_are_not_candidates(self):
        for status in (
            Request.STATUS_DRAFT,
            Request.STATUS_PROGRESS_1,
            Request.STATUS_PAYED,
            Request.STATUS_REJECTED,
            Request.STATUS_DELETED,
        ):
            self._request(status=status)
        expense = self._expense()
        self.assertEqual(self._candidate_ids(expense), [])

    # 7
    def test_linked_requests_are_not_candidates(self):
        other_expense = self._expense(note="другой расход")
        self._request(
            status=Request.STATUS_APPROVED,
            expense_ref_id=other_expense.pk,
            expense_ref_target=Request.EXPENSE_REF_TARGET_CARD,
        )
        self._request(status=Request.STATUS_APPROVED, expense_id="999")
        expense = self._expense()
        self.assertEqual(self._candidate_ids(expense), [])

    # 8
    def test_other_tenant_and_other_payment_type_are_not_candidates(self):
        other_tenant = Tenant.objects.create(name="Other", subdomain="cardcloseother", is_active=True)
        self._request(status=Request.STATUS_APPROVED, tenant=other_tenant)
        self._request(status=Request.STATUS_APPROVED, payment_type=Request.PAYMENT_TYPE_TRANSFER)
        expense = self._expense()
        self.assertEqual(self._candidate_ids(expense), [])

    # 9
    def test_created_at_window(self):
        expense_day = dt.datetime(2026, 11, 10, 12, 0, tzinfo=TASHKENT)
        too_old = self._request(status=Request.STATUS_APPROVED, created_at=expense_day - dt.timedelta(days=31))
        oldest_ok = self._request(status=Request.STATUS_APPROVED, created_at=expense_day - dt.timedelta(days=30))
        latest_ok = self._request(status=Request.STATUS_APPROVED, created_at=expense_day + dt.timedelta(days=3))
        too_new = self._request(status=Request.STATUS_APPROVED, created_at=expense_day + dt.timedelta(days=4))
        expense = self._expense(at=expense_day)

        ids = self._candidate_ids(expense)

        self.assertEqual(ids, [oldest_ok.pk, latest_ok.pk])
        self.assertNotIn(too_old.pk, ids)
        self.assertNotIn(too_new.pk, ids)

    # 10
    def test_configured_purpose_wins_then_oldest(self):
        older_other = self._request(
            status=Request.STATUS_APPROVED, purpose="Такси", created_at=dt.datetime(2026, 11, 1, 9, 0, tzinfo=TASHKENT)
        )
        younger_match = self._request(
            status=Request.STATUS_APPROVED, purpose=PURPOSE, created_at=dt.datetime(2026, 11, 8, 9, 0, tzinfo=TASHKENT)
        )
        expense = self._expense()
        self.assertEqual(self._candidate_ids(expense), [younger_match.pk, older_other.pk])

        result = process_card_expense_auto_request(expense.pk)
        self.assertEqual(result.request_id, younger_match.pk)

    def test_equal_purpose_picks_oldest(self):
        older = self._request(
            status=Request.STATUS_APPROVED, purpose=PURPOSE, created_at=dt.datetime(2026, 11, 1, 9, 0, tzinfo=TASHKENT)
        )
        self._request(
            status=Request.STATUS_APPROVED, purpose=PURPOSE, created_at=dt.datetime(2026, 11, 8, 9, 0, tzinfo=TASHKENT)
        )
        expense = self._expense()
        self.assertEqual(process_card_expense_auto_request(expense.pk).request_id, older.pk)

    # 11
    def test_two_expenses_two_requests_close_fifo(self):
        first_req = self._request(status=Request.STATUS_APPROVED, created_at=dt.datetime(2026, 11, 2, 9, 0, tzinfo=TASHKENT))
        second_req = self._request(status=Request.STATUS_APPROVED, created_at=dt.datetime(2026, 11, 3, 9, 0, tzinfo=TASHKENT))
        first_exp = self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        second_exp = self._expense(at=dt.datetime(2026, 11, 10, 15, 0, tzinfo=TASHKENT))

        r1 = process_card_expense_auto_request(first_exp.pk)
        r2 = process_card_expense_auto_request(second_exp.pk)

        self.assertEqual((r1.action, r1.request_id), (ACTION_CLOSED, first_req.pk))
        self.assertEqual((r2.action, r2.request_id), (ACTION_CLOSED, second_req.pk))
        first_req.refresh_from_db()
        second_req.refresh_from_db()
        self.assertEqual(first_req.expense_ref_id, first_exp.pk)
        self.assertEqual(second_req.expense_ref_id, second_exp.pk)

    def test_two_expenses_one_request_close_one_create_one(self):
        req = self._request(status=Request.STATUS_APPROVED)
        first_exp = self._expense(at=dt.datetime(2026, 11, 10, 9, 0, tzinfo=TASHKENT))
        second_exp = self._expense(at=dt.datetime(2026, 11, 10, 15, 0, tzinfo=TASHKENT))

        r1 = process_card_expense_auto_request(first_exp.pk)
        r2 = process_card_expense_auto_request(second_exp.pk)

        self.assertEqual((r1.action, r1.request_id), (ACTION_CLOSED, req.pk))
        self.assertEqual(r2.action, ACTION_CREATED)
        created = Request.objects.get(pk=r2.request_id)
        self.assertEqual(created.expense_ref_id, second_exp.pk)
        self.assertEqual(created.status, Request.STATUS_PAYED)

    # 12
    def test_suppressed_payment_step_is_not_closed(self):
        payment_step_guards.register_payment_step_suppressor(_suppress_all)
        req = self._approved_with_chain()
        expense = self._expense()

        result = process_card_expense_auto_request(expense.pk)

        self.assertEqual(result.action, ACTION_CREATED)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)
        self.assertIsNone(req.expense_ref_id)

    # 13
    def test_repeated_process_is_skipped(self):
        req = self._request(status=Request.STATUS_APPROVED)
        expense = self._expense()

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_CLOSED)
        again = process_card_expense_auto_request(expense.pk)

        self.assertEqual(again.action, ACTION_SKIPPED)
        self.assertEqual(self.payed_calls, [req.pk])
        self.assertEqual(RequestComment.objects.filter(request=req, created_by=self.system).count(), 1)

    # 14
    def test_disabled_config_keeps_request_approved(self):
        req = self._request(status=Request.STATUS_APPROVED)
        self.config.is_enabled = False
        self.config.save(update_fields=["is_enabled"])
        expense = self._expense()

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_SKIPPED)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)

    def test_match_text_mismatch_keeps_request_approved(self):
        req = self._request(status=Request.STATUS_APPROVED)
        self.config.match_text = "taxi"
        self.config.save(update_fields=["match_text"])
        expense = self._expense(note="Оплата рекламы")

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_SKIPPED)
        req.refresh_from_db()
        self.assertEqual(req.status, Request.STATUS_APPROVED)

    # 15
    def test_stale_candidate_is_skipped_under_lock(self):
        stale = self._request(status=Request.STATUS_APPROVED, created_at=dt.datetime(2026, 11, 2, 9, 0, tzinfo=TASHKENT))
        fresh = self._request(status=Request.STATUS_APPROVED, created_at=dt.datetime(2026, 11, 3, 9, 0, tzinfo=TASHKENT))
        expense = self._expense()

        def candidates_paid_meanwhile(**kwargs):
            # The candidate list was read before a payer marked `stale` as paid.
            Request.objects.filter(pk=stale.pk).update(status=Request.STATUS_PAYED)
            return Request.objects.filter(pk__in=[stale.pk, fresh.pk]).order_by("id")

        with patch.object(
            card_expense_pending_request_close,
            "pending_card_request_candidates",
            side_effect=candidates_paid_meanwhile,
        ):
            result = process_card_expense_auto_request(expense.pk)

        self.assertEqual((result.action, result.request_id), (ACTION_CLOSED, fresh.pk))
        stale.refresh_from_db()
        self.assertIsNone(stale.expense_ref_id)
        self.assertEqual(self.payed_calls, [fresh.pk])

    # 16
    def test_telegram_card_is_deactivated_not_sent(self):
        req = self._approved_with_chain()
        payment = Approval.objects.get(request=req, step_type=Approval.STEP_TYPE_PAYMENT)
        self.assertIsNotNone(payment.approver_recipient_id)
        message = TelegramMessage.objects.create(
            tenant=self.tenant, recipient_id="222", message_id=555, sent_at=timezone.now()
        )
        payment.telegram_message = message
        payment.save(update_fields=["telegram_message"])
        self.send_mock.reset_mock()
        self.deactivate_mock.reset_mock()
        expense = self._expense()

        self.assertEqual(process_card_expense_auto_request(expense.pk).action, ACTION_CLOSED)

        self.send_mock.assert_not_called()
        self.assertTrue(self.deactivate_mock.called)
        self.assertEqual(self.deactivate_mock.call_args.args[0].pk, message.pk)
