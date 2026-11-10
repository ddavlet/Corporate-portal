"""Tests for the delete_telegram_messages management command (gateway is mocked)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.modules.investments.models import InvestmentApprovalConfigStep, InvestmentReturnApproval, InvestReturn
from apps.modules.requests.models import Approval, Request
from apps.modules.telegram_approvals.models import Notification, TelegramMessage, TelegramMessageHistory
from apps.tenants.models import Tenant

User = get_user_model()

GATEWAY = "apps.modules.telegram_approvals.services.post_messaging_gateway"
MISSING_REQUEST_ID = 987654


@override_settings(MESSAGING_GATEWAY_SEND_URL="https://example.com/v1/messaging/send")
class DeleteTelegramMessagesCommandTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="DelCo", subdomain="delco", is_active=True)
        self.tenant.set_telegram_bot_token("111:AAATEST")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])
        self.user = User.objects.create_user(username="del-user", password="x", telegram_chat_id=424242)

    def _message(self, message_id=777, tenant=None, recipient_id="424242"):
        return TelegramMessage.objects.create(
            tenant=tenant or self.tenant,
            recipient_id=recipient_id,
            message_id=message_id,
            sent_at=timezone.now(),
        )

    def _history(self, message, *, action=TelegramMessageHistory.ACTION_SEND, success=True, payload=None):
        return TelegramMessageHistory.objects.create(
            telegram_message=message,
            action=action,
            message_id=message.message_id,
            recipient_id=message.recipient_id,
            request_payload=payload,
            success=success,
        )

    def _request(self):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="Delete test",
            status=Request.STATUS_PROGRESS_1,
            billing_date=timezone.now().date(),
            payment_type="Наличные",
        )

    def _run(self, *args):
        out, err = StringIO(), StringIO()
        call_command("delete_telegram_messages", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def _run_failing(self, *args):
        out, err = StringIO(), StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command("delete_telegram_messages", *args, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue(), str(ctx.exception)

    def _delete_history(self, message):
        return TelegramMessageHistory.objects.filter(
            telegram_message=message, action=TelegramMessageHistory.ACTION_DELETE
        )

    # (11)
    @patch(GATEWAY)
    def test_dry_run_prints_message_and_touches_nothing(self, mocked_post):
        tm = self._message(message_id=555)
        history_before = TelegramMessageHistory.objects.count()

        out, _ = self._run("--message-pk", str(tm.pk))

        mocked_post.assert_not_called()
        self.assertEqual(TelegramMessageHistory.objects.count(), history_before)
        self.assertIn(f"pk={tm.pk}", out)
        self.assertIn(f"tenant={self.tenant.pk}:delco", out)
        self.assertIn("recipient_id=424242", out)
        self.assertIn("message_id=555", out)
        self.assertIn("Будет удалено: 1", out)

    # (12)
    @patch(GATEWAY)
    def test_apply_deletes_via_gateway_and_keeps_row(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        tm = self._message(message_id=888)

        out, _ = self._run("--message-pk", str(tm.pk), "--apply")

        mocked_post.assert_called_once()
        self.assertEqual(mocked_post.call_args.kwargs["tenant"], self.tenant)
        payload = mocked_post.call_args.kwargs["payload"]
        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["message_id"], 888)
        self.assertEqual(payload["recipient_id"], "424242")
        self.assertEqual(payload["bot_token"], "111:AAATEST")
        history = self._delete_history(tm)
        self.assertEqual(history.count(), 1)
        self.assertTrue(history.get().success)
        self.assertTrue(TelegramMessage.objects.filter(pk=tm.pk).exists())
        self.assertIn("удалено", out)
        self.assertIn("Удалено: 1, ошибок: 0", out)

    # (13)
    @patch(GATEWAY)
    def test_request_id_finds_approval_and_notification_once(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        request_row = self._request()
        approval_msg = self._message(message_id=1001)
        notification_msg = self._message(message_id=1002)
        Approval.objects.create(
            request=request_row,
            approver_user=self.user,
            approver_recipient_id="424242",
            step=1,
            decision=Approval.DECISION_PENDING,
            telegram_message=approval_msg,
        )
        Notification.objects.create(
            tenant=self.tenant,
            kind=Notification.KIND_DRAFT,
            telegram_message=notification_msg,
            content_type=ContentType.objects.get_for_model(Request),
            object_id=request_row.pk,
        )
        # Card history also carries request_id — must not duplicate the message.
        self._history(approval_msg, payload={"action": "send_interactive", "request_id": request_row.pk})

        out, _ = self._run("--request-id", str(request_row.pk), "--apply")

        sent_ids = sorted(c.kwargs["payload"]["message_id"] for c in mocked_post.call_args_list)
        self.assertEqual(sent_ids, [1001, 1002])
        self.assertEqual(out.count(f"pk={approval_msg.pk} "), 1)
        self.assertIn("approval", out)
        self.assertIn("notification", out)
        self.assertIn("history", out)
        self.assertEqual(self._delete_history(approval_msg).count(), 1)
        self.assertEqual(self._delete_history(notification_msg).count(), 1)

    # (13) Approval and UserRequestApproval share one table: the same message is found by both
    # sources but must be deleted exactly once.
    @patch(GATEWAY)
    def test_request_id_message_found_by_both_approval_models_deleted_once(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        request_row = self._request()
        msg = self._message(message_id=1501)
        Approval.objects.create(
            request=request_row,
            approver_user=self.user,
            approver_recipient_id="424242",
            step=1,
            decision=Approval.DECISION_PENDING,
            telegram_message=msg,
        )

        out, _ = self._run("--request-id", str(request_row.pk), "--apply")

        self.assertIn("approval", out)
        self.assertIn("user_approval", out)
        self.assertEqual(out.count(f"pk={msg.pk} "), 1)
        mocked_post.assert_called_once()
        self.assertEqual(self._delete_history(msg).count(), 1)

    # (14) Request row is gone: history hits are shown but unconfirmed (tenant/entity unknown) and are
    # deleted only with --unconfirmed-history.
    @patch(GATEWAY)
    def test_request_id_of_deleted_request_found_via_history_int_and_str(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        msg_int = self._message(message_id=2001)
        msg_str = self._message(message_id=2002)
        other = self._message(message_id=2003)
        self._history(msg_int, payload={"action": "send_interactive", "request_id": MISSING_REQUEST_ID})
        self._history(msg_str, payload={"action": "send_interactive", "request_id": str(MISSING_REQUEST_ID)})
        self._history(other, payload={"action": "send_interactive", "request_id": MISSING_REQUEST_ID + 1})

        out, err = self._run("--request-id", str(MISSING_REQUEST_ID))

        mocked_post.assert_not_called()
        self.assertIn(f"pk={msg_int.pk} ", out)
        self.assertIn(f"pk={msg_str.pk} ", out)
        self.assertNotIn(f"pk={other.pk} ", out)
        self.assertEqual(out.count("[не подтверждено"), 2)
        self.assertIn("Будет удалено: 0", out)
        self.assertIn("пропущено (не подтверждено): 2", out)
        self.assertIn("--unconfirmed-history", err)

        out, _ = self._run("--request-id", str(MISSING_REQUEST_ID), "--apply")
        mocked_post.assert_not_called()
        self.assertIn("Удалено: 0, ошибок: 0", out)

        self._run("--request-id", str(MISSING_REQUEST_ID), "--apply", "--unconfirmed-history")
        sent_ids = sorted(c.kwargs["payload"]["message_id"] for c in mocked_post.call_args_list)
        self.assertEqual(sent_ids, [2001, 2002])

    # Soft-deleted / existing request: a history-only message of the request's tenant is confirmed.
    @patch(GATEWAY)
    def test_history_only_message_of_request_tenant_is_confirmed(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        request_row = self._request()
        msg = self._message(message_id=2101)
        self._history(msg, payload={"action": "send_interactive", "request_id": request_row.pk})

        out, err = self._run("--request-id", str(request_row.pk), "--apply")

        self.assertNotIn("[не подтверждено", out)
        self.assertEqual(err, "")
        mocked_post.assert_called_once()
        self.assertEqual(mocked_post.call_args.kwargs["payload"]["message_id"], 2101)

    def _invest_card(self, *, tenant, message_id):
        """Investment payout approval card whose history carries request_id=<InvestReturn.pk>."""
        invest_return = InvestReturn.objects.create(
            tenant=tenant,
            date=date(2026, 11, 10),
            billing_date=date(2026, 11, 1),
            sum=Decimal("1000.00"),
            currency="USD",
            type=InvestReturn.ReturnType.DIVIDEND,
            recipient=InvestReturn.Recipient.INVESTOR,
            created_by=self.user,
        )
        card = self._message(message_id=message_id, tenant=tenant)
        InvestmentReturnApproval.objects.create(
            tenant=tenant,
            invest_return=invest_return,
            step=1,
            step_type=InvestmentApprovalConfigStep.STEP_TYPE_CONFIRMATION,
            approver_user=self.user,
            telegram_message=card,
        )
        return invest_return, card

    # An investment card with history request_id == Request.pk (same tenant) must not be deleted.
    @patch(GATEWAY)
    def test_history_of_investment_card_with_same_id_not_candidate(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        request_row = self._request()
        approval_msg = self._message(message_id=2201)
        Approval.objects.create(
            request=request_row,
            approver_user=self.user,
            approver_recipient_id="424242",
            step=1,
            decision=Approval.DECISION_PENDING,
            telegram_message=approval_msg,
        )
        _, card = self._invest_card(tenant=self.tenant, message_id=2202)
        self._history(card, payload={"action": "send_interactive", "request_id": request_row.pk})

        out, _ = self._run("--request-id", str(request_row.pk), "--apply")

        self.assertNotIn(f"pk={card.pk} ", out)
        sent_ids = [c.kwargs["payload"]["message_id"] for c in mocked_post.call_args_list]
        self.assertEqual(sent_ids, [2201])
        self.assertEqual(self._delete_history(card).count(), 0)

    # Messages of another tenant with the same request_id in history (investment card or unlinked) are skipped.
    @patch(GATEWAY)
    def test_history_of_other_tenant_with_same_id_not_candidate(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        request_row = self._request()
        other_tenant = Tenant.objects.create(name="OtherCo", subdomain="otherco", is_active=True)
        _, card = self._invest_card(tenant=other_tenant, message_id=2301)
        unlinked = self._message(message_id=2302, tenant=other_tenant)
        for msg in (card, unlinked):
            self._history(msg, payload={"action": "send_interactive", "request_id": request_row.pk})

        out, err = self._run("--request-id", str(request_row.pk), "--apply")

        mocked_post.assert_not_called()
        self.assertNotIn(f"pk={card.pk} ", out)
        self.assertNotIn(f"pk={unlinked.pk} ", out)
        self.assertIn(f"Request id={request_row.pk}: сообщений не найдено", err)

    # (15)
    @patch(GATEWAY)
    def test_missing_pk_reported_others_processed_nonzero_exit(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        tm = self._message(message_id=3001)
        missing_pk = tm.pk + 1000

        out, err, summary = self._run_failing("--message-pk", f"{missing_pk},{tm.pk}", "--apply")

        self.assertIn(f"pk={missing_pk}: не найдено", err)
        mocked_post.assert_called_once()
        self.assertEqual(mocked_post.call_args.kwargs["payload"]["message_id"], 3001)
        self.assertTrue(self._delete_history(tm).get().success)
        self.assertIn("Удалено: 1, ошибок: 1", summary)

    # (16)
    @patch(GATEWAY)
    def test_gateway_error_recorded_others_processed_nonzero_exit(self, mocked_post):
        failed = self._message(message_id=4001)
        ok = self._message(message_id=4002)
        mocked_post.side_effect = [None, {"ok": True}]

        out, err, summary = self._run_failing("--message-pk", str(failed.pk), "--message-pk", str(ok.pk), "--apply")

        self.assertEqual(mocked_post.call_count, 2)
        self.assertIn(f"pk={failed.pk}: gateway вернул ошибку", err)
        self.assertFalse(self._delete_history(failed).get().success)
        self.assertTrue(self._delete_history(ok).get().success)
        self.assertIn("Удалено: 1, ошибок: 1", summary)

    # (17)
    @patch(GATEWAY)
    def test_empty_tenant_token_is_error_without_gateway_call(self, mocked_post):
        no_token = Tenant.objects.create(name="NoTok", subdomain="notok", is_active=True)
        tm = self._message(message_id=5001, tenant=no_token)

        out, err, summary = self._run_failing("--message-pk", str(tm.pk), "--apply")

        mocked_post.assert_not_called()
        self.assertIn("нет токена бота", err)
        self.assertEqual(self._delete_history(tm).count(), 0)
        self.assertIn("ошибок: 1", summary)

    # (18)
    def test_requires_selector(self):
        with self.assertRaises(CommandError):
            call_command("delete_telegram_messages", stdout=StringIO(), stderr=StringIO())
        with self.assertRaises(CommandError):
            call_command("delete_telegram_messages", "--apply", stdout=StringIO(), stderr=StringIO())

    def test_non_numeric_value_rejected(self):
        with self.assertRaises(CommandError):
            call_command("delete_telegram_messages", "--message-pk", "1,abc", stdout=StringIO(), stderr=StringIO())

    @patch(GATEWAY)
    def test_already_deleted_skipped_and_rerun_exits_zero(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        tm = self._message(message_id=6001)

        self._run("--message-pk", str(tm.pk), "--apply")
        self.assertEqual(mocked_post.call_count, 1)

        out, err = self._run("--message-pk", str(tm.pk), "--apply")

        self.assertEqual(mocked_post.call_count, 1)
        self.assertEqual(err, "")
        self.assertIn("[уже удалено]", out)
        self.assertIn("пропущено (уже удалено)", out)
        self.assertIn("Удалено: 0, ошибок: 0, пропущено (уже удалено): 1", out)
        self.assertEqual(self._delete_history(tm).count(), 1)

    # resend() reuses the TelegramMessage row with a new message_id: the new Telegram message is not deleted.
    @patch(GATEWAY)
    def test_message_resent_after_delete_is_deleted_again(self, mocked_post):
        mocked_post.return_value = {"ok": True}
        tm = self._message(message_id=6101)
        self._run("--message-pk", str(tm.pk), "--apply")
        tm.message_id = 6102
        tm.save(update_fields=["message_id"])

        out, _ = self._run("--message-pk", str(tm.pk))
        self.assertNotIn("[уже удалено]", out)
        self.assertIn("Будет удалено: 1", out)

        self._run("--message-pk", str(tm.pk), "--apply")

        sent_ids = [c.kwargs["payload"]["message_id"] for c in mocked_post.call_args_list]
        self.assertEqual(sent_ids, [6101, 6102])
        self.assertEqual(self._delete_history(tm).filter(success=True).count(), 2)
