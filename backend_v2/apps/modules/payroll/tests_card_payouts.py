"""Salary card payouts from the Kapitalbank payroll transit account (23106).

Acceptance criteria of docs/superpowers/plans/2026-11-13-payroll-card-payouts.md (numbers in test
names and comments). Bank responses go through the real KapitalbankClient parser with a fake
HTTP session, so the passport / INN / birth-date whitelist is exercised end to end.
"""

import copy
import datetime
import logging
import re
from datetime import date, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock, skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import DEFAULT_DB_ALIAS, connections
from django.forms.models import model_to_dict
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from apps.modules.bank_expenses.models import BankExpense
from apps.modules.cashier.models import CashExpense
from apps.modules.kapitalbank.client import KapitalbankClient
from apps.modules.kapitalbank.fixtures import (
    ACCOUNT_1,
    APILOGIN_WITH_ZP_JSON,
    BATCH_NUM,
    CARD_ACCOUNTS,
    CARD_NAMES,
    MFO,
    PII_MARKERS,
    TRANSIT_ACCOUNT,
    TRANSIT_DAY,
    TRANSIT_STATEMENT_JSON,
    WORKERS_JSON,
    ZP_JSON,
    KapitalbankFixtures,
)
from apps.modules.kapitalbank.models import (
    BankAccountLink,
    KapitalbankAlertSettings,
    KapitalbankConnection,
    SyncEvent,
)
from apps.modules.payroll import card_payouts
from apps.modules.payroll.card_sync import LOCK_ID, sync
from apps.modules.payroll.hooks import revert_document_to_draft_on_reject
from apps.modules.payroll.models import (
    BankPayrollEmployee,
    BankPayrollEmployeeAccount,
    Employee,
    PayrollBankEmployeeLink,
    PayrollCardBatch,
    PayrollCardPayout,
    PayrollCardSettings,
    PayrollDocument,
    PayrollExpectedCard,
)
from apps.modules.payroll.payouts import close_underpaid, create_payout_expense, payout_state
from apps.modules.payroll.services import (
    accept_document,
    cancel_draft_document,
    create_draft_document,
    current_request_for_document,
    update_draft_document,
)
from apps.modules.payroll.tests_workflow import make_payroll_approval_chain
from apps.modules.requests.approval_workflow import confirm_approval_by_id
from apps.modules.requests.models import Approval, Request
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account, get_or_create_cash_wallet
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

LOGIN = "IB#cardlogin"
PASSWORD = "Card-S3cret-pass"
NOW = datetime.datetime(2026, 10, 2, 7, 0, tzinfo=dt_timezone.utc)  # 12:00 in Tashkent
PAY_DAY = date(2026, 10, 2)
SEPTEMBER = date(2026, 9, 1)
AUGUST = date(2026, 8, 1)
TOTAL = Decimal("16808000.00")
EMPTY_STATEMENT = {"error": None, "result": {"content": [], "saldo_in": 0, "saldo_out": 0, "fin": 1}}


def _resp(payload):
    r = mock.Mock()
    r.status_code = 200
    r.json.return_value = copy.deepcopy(payload)
    return r


class FakeBankSession:
    """requests.Session stand-in for KapitalbankClient. statements[(account, dd.mm.yyyy)] is a
    queue: each fetch pops one, the last one repeats."""

    def __init__(self):
        self.calls = []
        self.statements = {(TRANSIT_ACCOUNT, TRANSIT_DAY): [TRANSIT_STATEMENT_JSON]}
        self.login = APILOGIN_WITH_ZP_JSON
        self.workers = WORKERS_JSON
        self.zp = {TRANSIT_DAY: ZP_JSON}
        self.errors = {}

    def post(self, url, json=None, headers=None, timeout=None):
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, json))
        if method in self.errors:
            return _resp(self.errors[method])
        if method == "GetDoc1C":
            queue = self.statements.get((json["account"], json["date"]))
            if not queue:
                return _resp(EMPTY_STATEMENT)
            return _resp(queue.pop(0) if len(queue) > 1 else queue[0])
        if method == "APILogin":
            return _resp(self.login)
        if method == "GetWorkers1C":
            return _resp(self.workers)
        if method == "GetZP1C":
            return _resp(self.zp.get(json["date"], {"error": None, "result": []}))
        raise AssertionError(f"unexpected bank method {method}")

    def count(self, method, **match):
        return sum(1 for m, body in self.calls if m == method and all(body.get(k) == v for k, v in match.items()))


def partial_statement(card_rows: int, *, with_batch: bool):
    content = TRANSIT_STATEMENT_JSON["result"]["content"]
    docs = content[:card_rows] + (content[-1:] if with_batch else [])
    return {**TRANSIT_STATEMENT_JSON, "result": {**TRANSIT_STATEMENT_JSON["result"], "content": docs}}


class _SyncMixin(KapitalbankFixtures):
    def setup_sync(self):
        self.make_fixtures()
        self.conn = self._connection(self.tenant)
        self.transit_link = self._transit_link(self.tenant)
        alert_settings = KapitalbankAlertSettings.load()
        alert_settings.recipient = self.owner
        alert_settings.save()
        self.bank = FakeBankSession()

    def _connection(self, tenant, *, enabled=True):
        conn = KapitalbankConnection(tenant=tenant, login=LOGIN, is_enabled=enabled)
        conn.set_password(PASSWORD)
        conn.save()
        return conn

    def _transit_link(self, tenant):
        return BankAccountLink.objects.create(
            tenant=tenant, account_no=TRANSIT_ACCOUNT, branch=MFO, name="Транзитный ЗП",
            decision=BankAccountLink.IGNORED, ignore_reason="транзитный счёт ЗП",
        )

    def factory(self, conn):
        return KapitalbankClient(conn.login, conn.get_password(), session=self.bank)

    def run_sync(self, mode="hourly", **kwargs):
        kwargs.setdefault("now", NOW)
        return sync(mode=mode, client_factory=self.factory, **kwargs)

    def bank_expense(self, tenant, wallet, *, doc_no=BATCH_NUM, day=PAY_DAY, amount=TOTAL):
        return BankExpense.objects.create(
            tenant=tenant, created_by_id=1, external_id="", row_no=1, doc_date=day, process_date=day,
            expense_year=day.year, expense_month=day.month, expense_day=day.day, doc_no=doc_no,
            debit_turnover=amount, payment_purpose="Перечисление заработной платы", wallet=wallet,
        )

    def other_connection(self):
        other = connections.create_connection(DEFAULT_DB_ALIAS)
        self.addCleanup(other.close)
        return other


class CardSyncTests(_SyncMixin, TestCase):
    def setUp(self):
        self.setup_sync()

    def test_statement_rows_stored_with_batch_and_nothing_else_created(self):
        # Criterion 1.
        expenses_before = BankExpense.objects.count()
        report = self.run_sync()
        self.assertEqual(report.payouts_created, 5)
        self.assertEqual(report.batches_created, 1)
        batch = PayrollCardBatch.objects.get()
        self.assertEqual(batch.amount, TOTAL)
        self.assertEqual(batch.num, BATCH_NUM)
        self.assertEqual(batch.payer_account, ACCOUNT_1)
        rows = list(PayrollCardPayout.objects.order_by("bank_doc_key"))
        self.assertEqual(len(rows), 5)
        self.assertEqual(sum(r.amount for r in rows), TOTAL)
        self.assertTrue(all(r.batch_id == batch.pk for r in rows))
        self.assertEqual({r.card_account for r in rows}, set(CARD_ACCOUNTS))
        self.assertTrue(all(r.paid_on == PAY_DAY for r in rows))
        self.assertEqual({r.name_from_purpose for r in rows}, set(CARD_NAMES))
        self.assertEqual(BankExpense.objects.count(), expenses_before)
        self.assertFalse(CashExpense.objects.exists())
        self.assertFalse(Request.objects.exists())

    def test_reload_is_idempotent(self):
        # Criterion 2: same statement, overlapping periods.
        self.run_sync()
        self.run_sync()
        self.run_sync("nightly")
        self.assertEqual(PayrollCardPayout.objects.count(), 5)
        self.assertEqual(PayrollCardBatch.objects.count(), 1)

    def test_shared_account_loaded_once_and_tenant_from_bank_expense(self):
        # Criterion 3: lemonfit / lemonhavo see the same transit account.
        havo = Tenant.objects.create(name="Havo", subdomain="havo", is_active=True)
        self._connection(havo)
        self._transit_link(havo)
        havo_wallet = get_or_create_bank_wallet_for_account(tenant=havo, account_no="20208000904843803099", mfo=MFO)
        self.bank_expense(havo, havo_wallet)
        self.run_sync()
        self.assertEqual(self.bank.count("GetDoc1C", account=TRANSIT_ACCOUNT, date=TRANSIT_DAY), 1)
        batch = PayrollCardBatch.objects.get()
        self.assertEqual(batch.tenant, havo)
        self.assertIsNotNone(batch.bank_expense_id)
        self.assertEqual(set(PayrollCardPayout.objects.values_list("tenant_id", flat=True)), {havo.pk})

    def test_rows_without_bank_expense_get_tenant_on_later_run(self):
        # Criterion 4.
        self.run_sync()
        self.assertEqual(set(PayrollCardPayout.objects.values_list("tenant_id", flat=True)), {None})
        self.bank_expense(self.tenant, self.wallet1)
        report = self.run_sync()
        self.assertEqual(report.tenants_resolved, 1)
        self.assertEqual(set(PayrollCardPayout.objects.values_list("tenant_id", flat=True)), {self.tenant.pk})

    def test_period_is_month_before_payment_not_purpose(self):
        # Criterion 5: paid 02.10.2026, purpose says «июль».
        self.run_sync()
        row = PayrollCardPayout.objects.first()
        self.assertIn("июль", row.purpose)
        self.assertEqual(row.period_month, SEPTEMBER)
        self.assertEqual(PayrollCardBatch.objects.get().period_month, SEPTEMBER)

    def test_bank_employee_from_directories_and_after_card_reissue(self):
        # Criterion 6.
        self.run_sync("nightly")
        by_account = {r.card_account: r for r in PayrollCardPayout.objects.select_related("bank_employee")}
        self.assertEqual(by_account[CARD_ACCOUNTS[0]].bank_employee.external_id, "E1001")
        self.assertEqual(by_account[CARD_ACCOUNTS[2]].bank_employee.masked_card, "5614********0003")
        self.assertEqual(by_account[CARD_ACCOUNTS[3]].bank_employee.external_id, "E1004")  # GetZP1C only
        unknown = by_account[CARD_ACCOUNTS[4]]
        self.assertIsNone(unknown.bank_employee_id)
        self.assertEqual(unknown.name_from_purpose, CARD_NAMES[4])

        new_account = "22618000900000000111"
        reissued = copy.deepcopy(WORKERS_JSON)
        reissued["result"][0]["acc"] = new_account
        self.bank.workers = reissued
        later = PayrollCardPayout.objects.create(
            transit_account=TRANSIT_ACCOUNT, bank_doc_key="LATER1", card_account=new_account, amount=Decimal("10"),
            paid_on=PAY_DAY, period_month=SEPTEMBER,
        )
        self.run_sync("nightly")
        later.refresh_from_db()
        first = by_account[CARD_ACCOUNTS[0]]
        first.refresh_from_db()
        self.assertEqual(later.bank_employee_id, first.bank_employee_id)
        self.assertEqual(
            set(BankPayrollEmployeeAccount.objects.filter(bank_employee=first.bank_employee).values_list("account_no", flat=True)),
            {CARD_ACCOUNTS[0], new_account},
        )

    def test_personal_data_never_stored_or_logged(self):
        # Criterion 7.
        self.bank.errors["GetZP1C"] = {"error": {"code": 70001, "message": "Нет данных"}}
        # The "apps" logger does not propagate to root (config/settings.py LOGGING): listen to it directly.
        with self.assertLogs("apps", level="DEBUG") as logs:
            # assertLogs fails when nothing is logged; a clean run may log nothing at all.
            logging.getLogger("apps.modules.payroll.tests").debug("pii scan start")
            self.run_sync("nightly")
        self.assertTrue(BankPayrollEmployee.objects.exists())
        texts = ["\n".join(logs.output)]
        for model in (BankPayrollEmployee, BankPayrollEmployeeAccount, PayrollCardBatch, PayrollCardPayout, SyncEvent):
            texts += [repr(model_to_dict(obj)) for obj in model.objects.all()]
        blob = "\n".join(texts)
        for marker in PII_MARKERS:
            self.assertNotIn(marker, blob)
        self.assertNotIn(PASSWORD, blob)

    def test_disabled_connection_loads_nothing(self):
        # Criterion 20.
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(is_enabled=False)
        report = self.run_sync()
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(report.accounts_ok + report.accounts_failed, 0)
        self.assertFalse(PayrollCardPayout.objects.exists())

    def test_bank_error_is_event_without_secrets(self):
        # Criterion 20.
        self.bank.errors["GetDoc1C"] = {"error": {"code": 61002, "message": "IP не разрешён"}}
        with self.assertLogs("apps.modules.payroll.card_sync", level="WARNING") as logs:
            report = self.run_sync()
        self.assertEqual(report.accounts_failed, 1)
        event = SyncEvent.objects.get(kind=SyncEvent.ERROR)
        self.assertEqual(event.payload["source"], "payroll_card")
        self.assertEqual(event.payload["code"], 61002)
        blob = f"{event.message} {event.payload} {logs.output}"
        for secret in (PASSWORD, LOGIN):
            self.assertNotIn(secret, blob)
        self.run_sync()
        self.assertEqual(SyncEvent.objects.filter(kind=SyncEvent.ERROR).count(), 1)  # one per day

    def test_rows_regrouped_when_sheet_completes_on_later_run(self):
        # The bank does not order content and may return part of the day: no sheet until the sums match.
        self.bank.statements[(TRANSIT_ACCOUNT, TRANSIT_DAY)] = [
            partial_statement(3, with_batch=True),
            TRANSIT_STATEMENT_JSON,
        ]
        self.run_sync()
        self.assertEqual(PayrollCardPayout.objects.count(), 3)
        self.assertFalse(PayrollCardPayout.objects.filter(batch__isnull=False).exists())
        report = self.run_sync()
        self.assertEqual(report.grouped, 5)
        self.assertEqual(PayrollCardPayout.objects.filter(batch=PayrollCardBatch.objects.get()).count(), 5)

    def test_ambiguous_day_rows_take_the_only_tenant(self):
        for n, amount in ((1, "100"), (2, "200")):
            PayrollCardBatch.objects.create(
                transit_account=TRANSIT_ACCOUNT, bank_doc_key=f"B{n}", num=str(n), doc_date=date(2026, 10, 1),
                amount=Decimal(amount), period_month=SEPTEMBER, tenant=self.tenant,
            )
        for n in range(3):
            PayrollCardPayout.objects.create(
                transit_account=TRANSIT_ACCOUNT, bank_doc_key=f"R{n}", card_account=CARD_ACCOUNTS[n],
                amount=Decimal("100"), paid_on=date(2026, 10, 1), period_month=SEPTEMBER,
            )
        self.bank.statements = {}
        self.run_sync()
        rows = PayrollCardPayout.objects.all()
        self.assertEqual({r.batch_id for r in rows}, {None})
        self.assertEqual({r.tenant_id for r in rows}, {self.tenant.pk})

    def test_batch_tenant_needs_the_same_sum(self):
        # Short payment numbers repeat: number and date alone must not give the sheet a tenant.
        self.bank_expense(self.tenant, self.wallet1, amount=TOTAL - Decimal("1"))
        self.run_sync()
        self.assertIsNone(PayrollCardBatch.objects.get().tenant_id)
        self.assertEqual(set(PayrollCardPayout.objects.values_list("tenant_id", flat=True)), {None})

    def test_batch_tenant_follows_payer_account(self):
        havo = Tenant.objects.create(name="Havo", subdomain="havo", is_active=True)
        self._transit_link(havo)
        havo_wallet = get_or_create_bank_wallet_for_account(tenant=havo, account_no="20208000904843803099", mfo=MFO)
        self.bank_expense(havo, havo_wallet)
        self.bank_expense(self.tenant, self.wallet1)
        BankAccountLink.objects.create(tenant=self.tenant, account_no=ACCOUNT_1, branch=MFO, name="Основной")
        self.run_sync()
        self.assertEqual(PayrollCardBatch.objects.get().tenant_id, self.tenant.pk)

    def _day_sheets_and_rows(self, rows):
        day = date(2026, 10, 1)
        for n, amount in ((1, "100"), (2, "200")):
            PayrollCardBatch.objects.create(
                transit_account=TRANSIT_ACCOUNT, bank_doc_key=f"B{n}", num=str(n), doc_date=day,
                amount=Decimal(amount), period_month=SEPTEMBER, tenant=self.tenant,
            )
        for n in range(rows):
            PayrollCardPayout.objects.create(
                transit_account=TRANSIT_ACCOUNT, bank_doc_key=f"R{n}", card_account=f"2261800090000009{n:04d}",
                amount=Decimal("100"), paid_on=day, period_month=SEPTEMBER,
            )
        self.bank.statements = {}

    def test_shared_account_free_rows_need_matching_sum(self):
        # A second tenant on the same transit account: rows of its missing sheet must not leak here.
        havo = Tenant.objects.create(name="Havo", subdomain="havo", is_active=True)
        self._transit_link(havo)
        self._day_sheets_and_rows(4)
        self.run_sync()
        self.assertEqual(set(PayrollCardPayout.objects.values_list("tenant_id", flat=True)), {None})

    def test_shared_account_free_rows_filling_the_sheets_take_the_tenant(self):
        havo = Tenant.objects.create(name="Havo", subdomain="havo", is_active=True)
        self._transit_link(havo)
        self._day_sheets_and_rows(3)
        self.run_sync()
        self.assertEqual(set(PayrollCardPayout.objects.values_list("tenant_id", flat=True)), {self.tenant.pk})

    def test_directory_not_loaded_for_unrelated_bank_clients(self):
        login = copy.deepcopy(APILOGIN_WITH_ZP_JSON)
        login["result"]["clients"][0]["zp_accs"] = [{"branch": 1158, "account": "23106000900000000999"}]
        self.bank.login = login
        with self.assertLogs("apps.modules.payroll.card_sync", level="WARNING") as logs:
            self.run_sync("nightly")
        self.assertEqual(self.bank.count("GetWorkers1C"), 0)
        self.assertFalse(BankPayrollEmployee.objects.exists())
        self.assertIn("directory skipped", "\n".join(logs.output))

    @patch("apps.modules.kapitalbank.alerts._send_text", return_value=True)
    def test_backfilled_rows_before_window_do_not_alert(self, send):
        old_day = PAY_DAY - timedelta(days=60)
        PayrollCardPayout.objects.create(
            transit_account=TRANSIT_ACCOUNT, bank_doc_key="OLD1", card_account=CARD_ACCOUNTS[0], amount=Decimal("10"),
            paid_on=old_day, period_month=date(2026, 7, 1),
        )
        PayrollCardPayout.objects.update(created_at=NOW - timedelta(days=3))
        self.bank.statements = {}
        report = self.run_sync()
        self.assertEqual(report.alerts, 0)
        send.assert_not_called()
        self.assertFalse(SyncEvent.objects.filter(kind=SyncEvent.MISSING_DOCS).exists())

    @patch("apps.modules.kapitalbank.alerts._send_text", return_value=True)
    def test_unassigned_rows_alert_owner_once(self, send):
        self.run_sync()
        PayrollCardPayout.objects.update(created_at=NOW - timedelta(days=3))
        later = NOW + timedelta(hours=1)
        report = self.run_sync(now=later)
        self.assertEqual(report.alerts, 1)
        self.assertEqual(send.call_count, 1)
        text = send.call_args.kwargs["text"]
        self.assertIn("5 шт.", text)
        for secret in (*CARD_NAMES, *CARD_ACCOUNTS):
            self.assertNotIn(secret, text)
        event = SyncEvent.objects.get(kind=SyncEvent.MISSING_DOCS)
        self.assertTrue(event.dedup_key.startswith(f"payroll_card_unassigned:{TRANSIT_ACCOUNT}:"))
        self.assertFalse(PayrollCardPayout.objects.filter(unassigned_alerted_at__isnull=True).exists())
        self.run_sync(now=later + timedelta(hours=1))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(SyncEvent.objects.filter(kind=SyncEvent.MISSING_DOCS).count(), 1)

    def test_busy_lock_skips_run(self):
        other = self.other_connection()
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [LOCK_ID])
        try:
            report = self.run_sync()
        finally:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
        self.assertTrue(report.skipped_locked)
        self.assertEqual(self.bank.calls, [])

    def test_dry_run_writes_nothing(self):
        report = self.run_sync("manual", since=date(2026, 10, 1), dry_run=True)
        self.assertEqual(report.payouts_created, 5)
        self.assertFalse(PayrollCardPayout.objects.exists())
        self.assertFalse(PayrollCardBatch.objects.exists())


class _PayrollCardMixin:
    """Portal-mode tenant with cash, payroll, an approval chain and card accounting from September."""

    START = SEPTEMBER

    def setup_payroll(self, subdomain="cardpay"):
        patcher = patch("apps.modules.telegram_approvals.services.TelegramDispatcher.send", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tenant = Tenant.objects.create(
            name="Card", subdomain=subdomain, is_active=True, payroll_payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL
        )
        for key in ("payroll", "cash", "wallets"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)
        self.system = User.objects.filter(pk=1).first() or User.objects.create_user(id=1, username="system", password="x")
        self.user = User.objects.create_user(username=f"{subdomain}-user", password="x")
        self.approver = User.objects.create_user(username=f"{subdomain}-approver", password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=self.approver, is_active=True)
        make_payroll_approval_chain(self.tenant, self.approver)
        self.alice = Employee.objects.create(tenant=self.tenant, full_name="Alice")
        self.bob = Employee.objects.create(tenant=self.tenant, full_name="Bob")
        self.wallet = get_or_create_cash_wallet(tenant=self.tenant, currency="UZS")
        self.card_settings = PayrollCardSettings.objects.create(tenant=self.tenant, card_start_period=self.START)
        self.bank_alice = BankPayrollEmployee.objects.create(bank_client_id="1", external_id="EA", full_name="ALICE")
        self.bank_bob = BankPayrollEmployee.objects.create(bank_client_id="1", external_id="EB", full_name="BOB")
        self._seq = 0

    def draft(self, lines, *, period=SEPTEMBER, kind="salary"):
        return create_draft_document(
            tenant=self.tenant, user=self.user, period_month=period, kind=kind,
            lines_data=[{"employee": e, "sum": Decimal(a)} for e, a in lines],
        )

    def approve(self, doc):
        req = accept_document(document=doc, actor=self.user)
        confirm_approval_by_id(
            tenant=self.tenant, approval_id=Approval.objects.get(request=req, step=1).id, approver_user_id=self.approver.id
        )
        doc.refresh_from_db()
        return doc

    def doc(self, lines, **kwargs):
        return self.approve(self.draft(lines, **kwargs))

    def reject(self, doc):
        req = current_request_for_document(doc)
        confirm_approval_by_id(
            tenant=self.tenant, approval_id=Approval.objects.get(request=req, step=1).id,
            approver_user_id=self.approver.id, decision=Approval.DECISION_REJECTED,
        )
        doc.refresh_from_db()
        return doc

    def card(self, amount, *, employee=None, bank_employee=None, document=None, period=SEPTEMBER, tenant="default"):
        self._seq += 1
        return PayrollCardPayout.objects.create(
            tenant=self.tenant if tenant == "default" else tenant,
            transit_account=TRANSIT_ACCOUNT,
            bank_doc_key=f"K{self._seq}",
            card_account=f"2261800090000001{self._seq:04d}",
            amount=Decimal(amount),
            paid_on=date(period.year + (period.month == 12), period.month % 12 + 1, 2),
            period_month=period,
            employee=employee,
            bank_employee=bank_employee,
            document=document,
        )

    def pay(self, doc, employee, amount):
        return create_payout_expense(
            document=doc, wallet_id=self.wallet.id, date=date(2026, 10, 5),
            items=[{"employee_id": employee.id, "amount": Decimal(amount)}], actor=self.user,
        )

    def link(self, bank_employee, employee):
        return PayrollBankEmployeeLink.objects.create(tenant=self.tenant, bank_employee=bank_employee, employee=employee)

    def row(self, state, employee):
        return next(r for r in state["employees"] if r["employee_id"] == employee.id)


class CardBalanceTests(_PayrollCardMixin, TestCase):
    def setUp(self):
        self.setup_payroll()

    def test_card_fact_reduces_cash_limit(self):
        # Criterion 12.
        doc = self.doc([(self.alice, "3000000")])
        self.card("2000000", employee=self.alice, document=doc)
        state = payout_state(doc)
        self.assertEqual(state["remaining_total"], Decimal("1000000.00"))
        self.assertEqual(state["card_paid_total"], Decimal("2000000.00"))
        self.assertEqual(state["paid_total"], Decimal("0"))
        self.assertEqual(self.row(state, self.alice)["cash_limit"], Decimal("1000000.00"))
        with self.assertRaises(ValidationError) as ctx:
            self.pay(doc, self.alice, "1000000.01")
        self.assertIn("можно выплатить не более 1000000.00", str(ctx.exception.detail))
        self.pay(doc, self.alice, "1000000")
        doc.refresh_from_db()
        # Covered by card + cash, but card auto-close is off: the document stays accepted.
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertEqual(payout_state(doc)["remaining_total"], Decimal("0"))

    def test_cash_payout_closes_with_card_when_auto_close_on(self):
        self.card_settings.auto_close_enabled = True
        self.card_settings.save()
        doc = self.doc([(self.alice, "3000000")])
        self.card("2000000", employee=self.alice, document=doc)
        req = current_request_for_document(doc)
        self.pay(doc, self.alice, "1000000")
        doc.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_CLOSED)
        self.assertEqual(req.status, Request.STATUS_PAYED)

    def test_expected_card_is_reserved_until_fact_arrives(self):
        # Criterion 13.
        doc = self.doc([(self.alice, "3000000")])
        PayrollExpectedCard.objects.create(document=doc, employee=self.alice, amount=Decimal("2000000"), is_manual=True)
        state = payout_state(doc)
        row = self.row(state, self.alice)
        self.assertEqual(row["remaining"], Decimal("3000000.00"))
        self.assertEqual(row["card_reserved"], Decimal("2000000.00"))
        self.assertEqual(row["cash_limit"], Decimal("1000000.00"))
        self.assertEqual(state["cash_limit_total"], Decimal("1000000.00"))
        with self.assertRaises(ValidationError):
            self.pay(doc, self.alice, "1000000.01")
        self.card("2000000", employee=self.alice, document=doc)
        row = self.row(payout_state(doc), self.alice)
        self.assertEqual(row["card_reserved"], Decimal("0"))
        self.assertEqual(row["cash_limit"], Decimal("1000000.00"))

    def test_everything_expected_on_card_blocks_cash(self):
        doc = self.doc([(self.alice, "3000000")])
        PayrollExpectedCard.objects.create(document=doc, employee=self.alice, amount=Decimal("3000000"), is_manual=True)
        state = payout_state(doc)
        self.assertFalse(state["can_pay"])
        self.assertEqual(state["reason"], "Остаток ожидается на карту.")

    def test_overpaid_in_state(self):
        # Criterion 15 (state).
        doc = self.doc([(self.alice, "3000000")])
        self.pay(doc, self.alice, "1500000")
        self.card("2000000", employee=self.alice, document=doc)
        state = payout_state(doc)
        row = self.row(state, self.alice)
        self.assertEqual(row["overpaid"], Decimal("500000.00"))
        self.assertEqual(state["overpaid_total"], Decimal("500000.00"))
        self.assertEqual(state["remaining_total"], Decimal("0"))

    def test_close_underpaid_counts_card_in_request_amount(self):
        doc = self.doc([(self.alice, "3000000"), (self.bob, "1000000")])
        self.card("2000000", employee=self.alice, document=doc)
        req = current_request_for_document(doc)
        close_underpaid(document=doc, actor=self.user, comment="Bob уволился")
        req.refresh_from_db()
        self.assertEqual(req.amount, Decimal("2000000.00"))
        self.assertEqual(req.status, Request.STATUS_PAYED)

    def test_reject_does_not_revert_document_with_card_rows(self):
        doc = self.approve(self.draft([(self.alice, "100")]))
        self.card("50", employee=self.alice, document=doc)
        revert_document_to_draft_on_reject(request_obj=current_request_for_document(doc))
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)

    def test_switched_off_tenant_keeps_attached_card_rows(self):
        # Clearing or moving card_start_period must not let the cash desk pay card money again:
        # attached rows still count, only the expected-card reserve goes away.
        doc = self.doc([(self.alice, "3000000")])
        self.card("2000000", employee=self.alice, document=doc)
        PayrollExpectedCard.objects.create(document=doc, employee=self.alice, amount=Decimal("2500000"))
        for start in (None, date(2026, 10, 1)):
            self.card_settings.card_start_period = start
            self.card_settings.save()
            state = payout_state(doc)
            row = self.row(state, self.alice)
            self.assertEqual(state["card_paid_total"], Decimal("2000000.00"))
            self.assertEqual(state["remaining_total"], Decimal("1000000.00"))
            self.assertEqual(row["card_reserved"], Decimal("0"))
            self.assertEqual(row["cash_limit"], Decimal("1000000.00"))
            with self.assertRaises(ValidationError):
                self.pay(doc, self.alice, "1000000.01")
        res_card = card_payouts.document_card_summary([doc.pk])[doc.pk]
        self.assertEqual(res_card["card_paid_total"], Decimal("2000000.00"))

    def test_document_before_start_is_unchanged(self):
        doc = self.doc([(self.alice, "3000000")], period=AUGUST)
        PayrollExpectedCard.objects.create(document=doc, employee=self.alice, amount=Decimal("2000000"))
        self.card("2000000", employee=self.alice, period=AUGUST)
        card_payouts.attach_pending(now=timezone.now())
        state = payout_state(doc)
        self.assertEqual(state["remaining_total"], Decimal("3000000.00"))
        self.assertEqual(state["cash_limit_total"], Decimal("3000000.00"))

    def test_overpaid_employee_does_not_hide_other_debt(self):
        # Card money is not capped by the employee's balance: Alice's overpayment must not cover Bob.
        self.card_settings.auto_close_enabled = True
        self.card_settings.save()
        doc = self.doc([(self.alice, "3000000"), (self.bob, "500000")])
        self.link(self.bank_alice, self.alice)
        self.card("3500000", bank_employee=self.bank_alice)
        self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 1)
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertEqual(current_request_for_document(doc).status, Request.STATUS_APPROVED)
        state = payout_state(doc)
        self.assertEqual(state["remaining_total"], Decimal("500000.00"))
        self.assertEqual(state["overpaid_total"], Decimal("500000.00"))
        self.assertEqual(card_payouts.close_sweep(), 0)
        req = current_request_for_document(doc)
        close_underpaid(document=doc, actor=self.user, comment="Bob получит в следующем месяце")
        doc.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_CLOSED)
        self.assertIsNotNone(doc.closed_underpaid_at)
        self.assertEqual(req.amount, Decimal("3500000.00"))

    def test_cash_payout_does_not_close_while_other_employee_unpaid(self):
        self.card_settings.auto_close_enabled = True
        self.card_settings.save()
        doc = self.doc([(self.alice, "1000000"), (self.bob, "500000")])
        self.card("1500000", employee=self.alice, document=doc)
        self.pay(doc, self.bob, "400000")
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertEqual(payout_state(doc)["remaining_total"], Decimal("100000.00"))


class CardAttachTests(_PayrollCardMixin, TestCase):
    def setUp(self):
        self.setup_payroll()

    def test_linked_row_waits_and_attaches_after_accept(self):
        # Criterion 11.
        draft = self.draft([(self.alice, "3000000")])
        self.link(self.bank_alice, self.alice)
        row = self.card("2000000", bank_employee=self.bank_alice)
        card_payouts.attach_pending(now=timezone.now())
        row.refresh_from_db()
        self.assertIsNone(row.document_id)
        waiting = card_payouts.attention_state(self.tenant)["awaiting_document"]
        self.assertEqual([w["payout_id"] for w in waiting], [row.pk])
        with self.captureOnCommitCallbacks(execute=True):
            accept_document(document=draft, actor=self.user)
        row.refresh_from_db()
        # The request is still in approval and may be rejected: no card money on the document yet.
        self.assertIsNone(row.document_id)
        self.assertEqual(row.employee_id, self.alice.pk)
        confirm_approval_by_id(
            tenant=self.tenant,
            approval_id=Approval.objects.get(request=current_request_for_document(draft), step=1).id,
            approver_user_id=self.approver.id,
        )
        self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 1)
        row.refresh_from_db()
        self.assertEqual(row.document_id, draft.pk)
        self.assertEqual(card_payouts.attention_state(self.tenant)["awaiting_document"], [])

    def test_rejected_request_returns_draft_with_card_rows_waiting(self):
        draft = self.draft([(self.alice, "3000000")])
        self.link(self.bank_alice, self.alice)
        row = self.card("2000000", bank_employee=self.bank_alice)
        with self.captureOnCommitCallbacks(execute=True):
            accept_document(document=draft, actor=self.user)
        card_payouts.attach_pending(now=timezone.now())
        doc = self.reject(draft)
        self.assertEqual(doc.status, PayrollDocument.STATUS_DRAFT)
        row.refresh_from_db()
        self.assertIsNone(row.document_id)
        update_draft_document(
            document=doc, period_month=SEPTEMBER, kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("2500000")}],
        )
        self.approve(doc)
        self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 1)
        row.refresh_from_db()
        self.assertEqual(row.document_id, doc.pk)

    def test_attach_rechecks_document_under_lock(self):
        doc = self.doc([(self.alice, "3000000")])
        row = self.card("100", employee=self.alice)
        # pick_document saw it accepted; a reject moved it back to draft before the lock.
        PayrollDocument.objects.filter(pk=doc.pk).update(status=PayrollDocument.STATUS_DRAFT)
        self.assertFalse(card_payouts._attach_one(payout_id=row.pk, document=doc, now=timezone.now()))
        row.refresh_from_db()
        self.assertIsNone(row.document_id)

    def test_draft_with_card_rows_cannot_be_changed(self):
        draft = self.draft([(self.alice, "3000000")])
        self.card("100", employee=self.alice, document=draft)
        with self.assertRaises(ValidationError):
            update_draft_document(
                document=draft, period_month=SEPTEMBER, kind="salary",
                lines_data=[{"employee": self.alice, "sum": Decimal("1")}],
            )
        with self.assertRaises(ValidationError):
            cancel_draft_document(document=draft)

    def test_stuck_rows_pick_document_once_per_employee_and_period(self):
        for _ in range(3):
            self.card("100", employee=self.alice)
        with patch("apps.modules.payroll.card_payouts.pick_document", wraps=card_payouts.pick_document) as pick:
            self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 0)
        self.assertEqual(pick.call_count, 1)

    def test_expected_card_dropped_when_draft_becomes_advance(self):
        self.card("2000000", employee=self.alice, period=AUGUST)
        draft = self.draft([(self.alice, "3000000")])
        self.assertTrue(PayrollExpectedCard.objects.filter(document=draft, amount=Decimal("2000000")).exists())
        update_draft_document(
            document=draft, period_month=SEPTEMBER, kind="advance",
            lines_data=[{"employee": self.alice, "sum": Decimal("3000000")}],
        )
        state = payout_state(self.approve(draft))
        row = self.row(state, self.alice)
        self.assertEqual(row["card_reserved"], Decimal("0"))
        self.assertEqual(row["cash_limit"], row["remaining"])
        self.assertEqual(state["card_expected_total"], Decimal("0"))

    def test_expected_card_of_removed_employee_is_ignored(self):
        self.card("2000000", employee=self.alice, period=AUGUST)
        self.card("500000", employee=self.bob, period=AUGUST)
        draft = self.draft([(self.alice, "3000000"), (self.bob, "1000000")])
        update_draft_document(
            document=draft, period_month=SEPTEMBER, kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("3000000")}],
        )
        doc = self.approve(draft)
        state = payout_state(doc)
        self.assertEqual(state["card_expected_total"], Decimal("2000000.00"))
        missing = card_payouts.attention_state(self.tenant, today=date(2026, 10, 15))["missing_card"]
        self.assertEqual([m["employee_id"] for m in missing], [self.alice.pk])

    def test_expected_card_follows_draft_update(self):
        self.card("500000", employee=self.bob, period=AUGUST)
        draft = self.draft([(self.alice, "3000000")])
        self.assertFalse(PayrollExpectedCard.objects.filter(document=draft).exists())
        update_draft_document(
            document=draft, period_month=SEPTEMBER, kind="salary",
            lines_data=[{"employee": self.alice, "sum": Decimal("3000000")}, {"employee": self.bob, "sum": Decimal("1")}],
        )
        self.assertEqual(PayrollExpectedCard.objects.get(document=draft).employee_id, self.bob.pk)

    def test_overpaid_group_limited_to_last_periods(self):
        self.card_settings.card_start_period = date(2025, 1, 1)
        self.card_settings.save()
        old = self.doc([(self.alice, "100")], period=date(2025, 8, 1))
        self.card("200", employee=self.alice, document=old, period=date(2025, 8, 1))
        recent = self.doc([(self.alice, "100")])
        self.card("200", employee=self.alice, document=recent)
        overpaid = card_payouts.attention_state(self.tenant)["overpaid"]
        self.assertEqual([o["document_id"] for o in overpaid], [recent.pk])

    def test_name_suggestions_only_for_shown_rows(self):
        for _ in range(3):
            self.card("100")
        with patch.object(card_payouts, "ATTENTION_LIMIT", 2), patch(
            "apps.modules.payroll.card_payouts.suggest_employee", return_value=None
        ) as suggest:
            state = card_payouts.attention_state(self.tenant)
        self.assertEqual(suggest.call_count, 2)
        self.assertEqual(len(state["unlinked"]), 2)
        self.assertEqual(state["count"], 3)
        # The full size of every group, so the screen can say «Показаны первые 2 из 3».
        self.assertEqual(state["counts"], {"unlinked": 3, "awaiting_document": 0, "missing_card": 0, "overpaid": 0})

    def test_expected_card_prefilled_from_last_month_and_manual_kept(self):
        # Criterion 14: August is before the start (history) and still feeds September's prefill.
        self.card("2000000", employee=self.alice, period=AUGUST)
        self.link(self.bank_bob, self.bob)
        self.card("500000", bank_employee=self.bank_bob, period=AUGUST)
        draft = self.draft([(self.alice, "3000000"), (self.bob, "1000000")])
        expected = {e.employee_id: e for e in PayrollExpectedCard.objects.filter(document=draft)}
        self.assertEqual(expected[self.alice.pk].amount, Decimal("2000000.00"))
        self.assertFalse(expected[self.alice.pk].is_manual)
        self.assertEqual(expected[self.bob.pk].amount, Decimal("500000.00"))
        card_payouts.set_expected(
            document=draft, items=[{"employee_id": self.alice.pk, "amount": Decimal("1500000")}], actor=self.user
        )
        self.card("700000", employee=self.bob, period=AUGUST)
        with self.captureOnCommitCallbacks(execute=True):
            accept_document(document=draft, actor=self.user)
        expected = {e.employee_id: e for e in PayrollExpectedCard.objects.filter(document=draft)}
        self.assertEqual(expected[self.alice.pk].amount, Decimal("1500000.00"))
        self.assertTrue(expected[self.alice.pk].is_manual)
        self.assertEqual(expected[self.bob.pk].amount, Decimal("1200000.00"))  # recalculated on accept
        # History rows were not attached anywhere.
        self.assertFalse(PayrollCardPayout.objects.filter(period_month=AUGUST, document__isnull=False).exists())

    def test_set_expected_marks_manual_only_changed_amounts(self):
        # The modal sends every row; an unchanged prefilled amount must keep following last month's fact.
        self.card("2000000", employee=self.alice, period=AUGUST)
        self.card("500000", employee=self.bob, period=AUGUST)
        draft = self.draft([(self.alice, "3000000"), (self.bob, "1000000")])
        card_payouts.set_expected(
            document=draft,
            items=[
                {"employee_id": self.alice.pk, "amount": Decimal("1500000")},
                {"employee_id": self.bob.pk, "amount": Decimal("500000.00")},
            ],
            actor=self.user,
        )
        expected = {e.employee_id: e for e in PayrollExpectedCard.objects.filter(document=draft)}
        self.assertTrue(expected[self.alice.pk].is_manual)
        self.assertFalse(expected[self.bob.pk].is_manual)
        self.card("700000", employee=self.bob, period=AUGUST)
        with self.captureOnCommitCallbacks(execute=True):
            accept_document(document=draft, actor=self.user)
        expected = {e.employee_id: e for e in PayrollExpectedCard.objects.filter(document=draft)}
        self.assertEqual(expected[self.alice.pk].amount, Decimal("1500000.00"))
        self.assertEqual(expected[self.bob.pk].amount, Decimal("1200000.00"))  # still prefilled, recalculated

    def test_prefill_error_never_fails_accept(self):
        with patch("apps.modules.payroll.card_payouts.prefill_expected", side_effect=RuntimeError("boom")):
            with self.assertLogs("apps.modules.payroll.card_payouts", level="ERROR") as logs:
                draft = self.draft([(self.alice, "100")])
                with self.captureOnCommitCallbacks(execute=True):
                    accept_document(document=draft, actor=self.user)
        draft.refresh_from_db()
        self.assertEqual(draft.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertIn("prefill failed", "\n".join(logs.output))

    def _covered_doc(self):
        doc = self.doc([(self.alice, "3000000")])
        self.pay(doc, self.alice, "1000000")
        self.link(self.bank_alice, self.alice)
        self.card("2000000", bank_employee=self.bank_alice)
        return doc

    def test_card_closes_document_when_flag_on(self):
        # Criterion 16.
        self.card_settings.auto_close_enabled = True
        self.card_settings.save()
        doc = self._covered_doc()
        req = current_request_for_document(doc)
        self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 1)
        doc.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_CLOSED)
        self.assertEqual(req.status, Request.STATUS_PAYED)

    def test_card_does_not_close_document_when_flag_off_until_sweep(self):
        doc = self._covered_doc()
        card_payouts.attach_pending(now=timezone.now())
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        self.assertEqual(card_payouts.close_sweep(), 0)
        self.card_settings.auto_close_enabled = True
        self.card_settings.save()
        self.assertEqual(card_payouts.close_sweep(), 1)
        doc.refresh_from_db()
        self.assertEqual(doc.status, PayrollDocument.STATUS_CLOSED)

    def test_two_salary_documents_card_goes_to_one_with_balance(self):
        first = self.doc([(self.alice, "100")])
        self.pay(first, self.alice, "100")  # fully paid by cash (closes)
        second = self.doc([(self.alice, "500")])
        row = self.card("300", employee=self.alice)
        card_payouts.attach_pending(now=timezone.now())
        row.refresh_from_db()
        self.assertEqual(row.document_id, second.pk)

    def test_advance_and_bonus_never_get_card(self):
        self.doc([(self.alice, "500")], kind="advance")
        self.doc([(self.alice, "500")], kind="bonus")
        row = self.card("300", employee=self.alice)
        self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 0)
        row.refresh_from_db()
        self.assertIsNone(row.document_id)

    def test_nothing_happens_without_start_period(self):
        self.card_settings.card_start_period = None
        self.card_settings.save()
        self.card("2000000", employee=self.alice, period=AUGUST)
        draft = self.draft([(self.alice, "3000000")])
        self.assertFalse(PayrollExpectedCard.objects.filter(document=draft).exists())
        doc = self.approve(draft)
        row = self.card("100", employee=self.alice)
        self.assertEqual(card_payouts.attach_pending(now=timezone.now()), 0)
        row.refresh_from_db()
        self.assertIsNone(row.document_id)
        self.assertFalse(card_payouts.attention_state(self.tenant)["enabled"])
        self.assertEqual(payout_state(doc)["cash_limit_total"], Decimal("3000000.00"))

    def test_rows_before_start_stay_unattached_and_hidden(self):
        doc = self.doc([(self.alice, "500")], period=AUGUST)
        row = self.card("300", employee=self.alice, period=AUGUST)
        card_payouts.attach_pending(now=timezone.now())
        row.refresh_from_db()
        doc.refresh_from_db()
        self.assertIsNone(row.document_id)
        self.assertEqual(doc.status, PayrollDocument.STATUS_ACCEPTED)
        state = card_payouts.attention_state(self.tenant)
        self.assertEqual(state["count"], 0)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class CardApiTests(_PayrollCardMixin, APITestCase):
    def setUp(self):
        self.setup_payroll(subdomain="cardapi")
        self.host = "cardapi.example.com"
        self.director = self._user("card-director", TenantUserRole.ROLE_DIRECTOR)
        self.cashier = self._user("card-cashier", TenantUserRole.ROLE_CASHIER)
        self.accountant = self._user("card-accountant", TenantUserRole.ROLE_ACCOUNTANT)
        self.sherzod = Employee.objects.create(tenant=self.tenant, full_name="Исмоилов Шерзод")
        self.bank_sherzod = BankPayrollEmployee.objects.create(
            bank_client_id="1", external_id="ES", full_name="ISMOILOV SHERZOD BAXTIYOROVICH", masked_card="8600********1111"
        )

    def _user(self, username, role):
        user = User.objects.create_user(username=username, password="x")
        TenantMembership.objects.create(tenant=self.tenant, user=user, is_active=True)
        TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
        return user

    def get(self, url, user=None):
        self.client.force_authenticate(user or self.director)
        return self.client.get(url, HTTP_HOST=self.host)

    def post(self, url, body, user=None, method="post"):
        self.client.force_authenticate(user or self.director)
        return getattr(self.client, method)(url, body, format="json", HTTP_HOST=self.host)

    def test_unlinked_rows_with_candidate_and_link(self):
        # Criteria 8, 9, 18.
        linked_row = self.card("1000000", bank_employee=self.bank_sherzod)
        orphan = self.card("700000")
        orphan.name_from_purpose = "NOMALUM JASUR"
        orphan.save()
        res = self.get("/api/payroll/card-payouts/attention/")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.data["enabled"])
        self.assertEqual(res.data["count"], 2)
        by_id = {r["payout_id"]: r for r in res.data["unlinked"]}
        row = by_id[linked_row.pk]
        self.assertEqual(row["bank_full_name"], "ISMOILOV SHERZOD BAXTIYOROVICH")
        self.assertEqual(row["masked_card"], "8600********1111")
        self.assertEqual(row["candidate"], {"id": self.sherzod.pk, "full_name": "Исмоилов Шерзод"})
        self.assertNotIn(linked_row.card_account, str(res.data))
        self.assertIsNone(by_id[orphan.pk]["bank_employee_id"])
        self.assertEqual(by_id[orphan.pk]["name_from_purpose"], "NOMALUM JASUR")

        res = self.post(
            "/api/payroll/bank-employee-links/", {"bank_employee_id": self.bank_sherzod.pk, "employee_id": self.sherzod.pk}
        )
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data["full_name"], "Исмоилов Шерзод")
        linked_row.refresh_from_db()
        self.assertEqual(linked_row.employee_id, self.sherzod.pk)
        future = self.card("5", bank_employee=self.bank_sherzod)
        card_payouts.fill_employees_from_links(tenant=self.tenant)
        future.refresh_from_db()
        self.assertEqual(future.employee_id, self.sherzod.pk)

        res = self.post(
            "/api/payroll/bank-employee-links/", {"bank_employee_id": self.bank_sherzod.pk, "employee_id": self.alice.pk}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("уже привязан к «Исмоилов Шерзод»", str(res.data))
        self.assertEqual(self.get("/api/payroll/card-payouts/attention/").data["count"], 1)

    def test_assign_row_without_bank_employee(self):
        doc = self.doc([(self.alice, "3000000")])
        orphan = self.card("2000000")
        res = self.post(f"/api/payroll/card-payouts/{orphan.pk}/assign/", {"employee_id": self.alice.pk})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data, {"payout_id": orphan.pk, "employee_id": self.alice.pk, "document_id": doc.pk})
        self.assertEqual(Decimal(payout_state(doc)["remaining_total"]), Decimal("1000000.00"))
        res = self.post(f"/api/payroll/card-payouts/{orphan.pk}/assign/", {"employee_id": self.bob.pk})
        self.assertEqual(res.status_code, 400)
        self.assertIn("уже отнесена", str(res.data))
        with_bank = self.card("10", bank_employee=self.bank_sherzod)
        res = self.post(f"/api/payroll/card-payouts/{with_bank.pk}/assign/", {"employee_id": self.alice.pk})
        self.assertEqual(res.status_code, 400)
        self.assertIn("используйте привязку", str(res.data))

    def test_overpaid_group_list_and_detail(self):
        # Criterion 15 (list) and the «Переплаты» group.
        doc = self.doc([(self.alice, "3000000")])
        self.pay(doc, self.alice, "1500000")
        self.card("2000000", employee=self.alice, document=doc)
        res = self.get("/api/payroll/card-payouts/attention/")
        self.assertEqual(res.data["count"], 1)
        [item] = res.data["overpaid"]
        self.assertEqual(item["document_id"], doc.pk)
        self.assertEqual(
            {k: Decimal(item[k]) for k in ("accrued", "cash", "card", "overpaid")},
            {"accrued": Decimal("3000000"), "cash": Decimal("1500000"), "card": Decimal("2000000"), "overpaid": Decimal("500000")},
        )
        res = self.get("/api/payroll/documents/")
        row = next(r for r in res.data["results"] if r["id"] == doc.pk)
        self.assertEqual(Decimal(row["overpaid_total"]), Decimal("500000"))
        self.assertEqual(Decimal(row["card_paid_total"]), Decimal("2000000"))
        res = self.get(f"/api/payroll/documents/{doc.pk}/")
        self.assertEqual(Decimal(res.data["remaining_total"]), Decimal("0"))
        self.assertEqual(Decimal(res.data["overpaid_total"]), Decimal("500000"))

    def test_detail_remaining_is_per_employee(self):
        doc = self.doc([(self.alice, "3000000"), (self.bob, "500000")])
        self.card("3500000", employee=self.alice, document=doc)
        res = self.get(f"/api/payroll/documents/{doc.pk}/")
        self.assertEqual(Decimal(res.data["remaining_total"]), Decimal("500000"))
        self.assertEqual(Decimal(res.data["overpaid_total"]), Decimal("500000"))

    def test_no_overpaid_group_without_overpayment(self):
        doc = self.doc([(self.alice, "3000000")])
        self.card("2000000", employee=self.alice, document=doc)
        res = self.get("/api/payroll/card-payouts/attention/")
        self.assertEqual(res.data["overpaid"], [])
        self.assertEqual(res.data["count"], 0)

    def test_missing_card_from_15th(self):
        # Criterion 17.
        doc = self.doc([(self.alice, "3000000"), (self.bob, "1000000")])
        PayrollExpectedCard.objects.create(document=doc, employee=self.alice, amount=Decimal("1000000"))
        PayrollExpectedCard.objects.create(document=doc, employee=self.bob, amount=Decimal("500000"))
        self.card("500000", employee=self.bob)
        with patch("apps.modules.payroll.card_payouts.timezone.localdate", return_value=date(2026, 10, 14)):
            self.assertEqual(self.get("/api/payroll/card-payouts/attention/").data["missing_card"], [])
        with patch("apps.modules.payroll.card_payouts.timezone.localdate", return_value=date(2026, 10, 15)):
            res = self.get("/api/payroll/card-payouts/attention/")
        self.assertEqual([(m["employee_id"], Decimal(m["expected"])) for m in res.data["missing_card"]], [(self.alice.pk, Decimal("1000000"))])

    def test_payable_documents_use_cash_limit(self):
        doc = self.doc([(self.alice, "3000000")])
        self.card("2000000", employee=self.alice, document=doc)
        res = self.get("/api/payroll/payable-documents/", self.cashier)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual([(d["id"], Decimal(d["remaining_total"])) for d in res.data], [(doc.pk, Decimal("1000000"))])

    def test_expected_card_endpoint(self):
        doc = self.doc([(self.alice, "3000000")])
        url = f"/api/payroll/documents/{doc.pk}/expected-card/"
        res = self.post(url, {"items": [{"employee_id": self.alice.pk, "amount": "2000000"}]}, method="put")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(Decimal(res.data["cash_limit_total"]), Decimal("1000000"))
        self.assertTrue(PayrollExpectedCard.objects.get(document=doc).is_manual)
        for items in (
            [{"employee_id": self.alice.pk, "amount": "-1"}],
            [{"employee_id": self.bob.pk, "amount": "1"}],
        ):
            self.assertEqual(self.post(url, {"items": items}, method="put").status_code, 400, items)
        PayrollDocument.objects.filter(pk=doc.pk).update(status=PayrollDocument.STATUS_CLOSED)
        res = self.post(url, {"items": [{"employee_id": self.alice.pk, "amount": "1"}]}, method="put")
        self.assertEqual(res.status_code, 400)

    def test_cashier_sees_card_sums_in_payout_state_only(self):
        doc = self.doc([(self.alice, "3000000")])
        self.card("2000000", employee=self.alice, document=doc)
        res = self.get(f"/api/payroll/documents/{doc.pk}/payout-state/", self.cashier)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Decimal(res.data["card_paid_total"]), Decimal("2000000"))
        self.assertEqual(Decimal(res.data["employees"][0]["cash_limit"]), Decimal("1000000"))
        orphan = self.card("1")
        for method, url, body in (
            ("get", "/api/payroll/card-payouts/attention/", None),
            ("post", "/api/payroll/bank-employee-links/", {"bank_employee_id": self.bank_sherzod.pk, "employee_id": self.sherzod.pk}),
            ("post", f"/api/payroll/card-payouts/{orphan.pk}/assign/", {"employee_id": self.alice.pk}),
            ("put", f"/api/payroll/documents/{doc.pk}/expected-card/", {"items": []}),
        ):
            self.client.force_authenticate(self.cashier)
            kwargs = {"HTTP_HOST": self.host}
            if body is not None:
                kwargs["format"] = "json"
                res = getattr(self.client, method)(url, body, **kwargs)
            else:
                res = getattr(self.client, method)(url, **kwargs)
            self.assertEqual(res.status_code, 403, url)

    def test_forbidden_without_role_or_module(self):
        # Criterion 10.
        self.assertEqual(self.get("/api/payroll/card-payouts/attention/", self.accountant).status_code, 403)
        res = self.post(
            "/api/payroll/bank-employee-links/",
            {"bank_employee_id": self.bank_sherzod.pk, "employee_id": self.sherzod.pk},
            self.accountant,
        )
        self.assertEqual(res.status_code, 403)
        TenantModuleConfig.objects.filter(tenant=self.tenant, module_key="payroll").update(is_enabled=False)
        self.assertEqual(self.get("/api/payroll/card-payouts/attention/").status_code, 403)

    def test_legacy_tenant_is_disabled(self):
        self.card("1", bank_employee=self.bank_sherzod)
        Tenant.objects.filter(pk=self.tenant.pk).update(payroll_payout_mode=Tenant.PAYROLL_PAYOUT_MODE_LEGACY)
        res = self.get("/api/payroll/card-payouts/attention/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["enabled"])
        self.assertEqual(res.data["count"], 0)

    def test_foreign_objects_are_404(self):
        other = Tenant.objects.create(
            name="Other", subdomain="cardother", is_active=True, payroll_payout_mode=Tenant.PAYROLL_PAYOUT_MODE_PORTAL
        )
        stranger = Employee.objects.create(tenant=other, full_name="Stranger")
        foreign_bank = BankPayrollEmployee.objects.create(bank_client_id="2", external_id="EX", full_name="X")
        foreign_row = self.card("1", bank_employee=foreign_bank, tenant=other)
        foreign_doc = PayrollDocument.objects.create(
            tenant=other, status=PayrollDocument.STATUS_ACCEPTED, payout_mode=PayrollDocument.PAYOUT_MODE_PORTAL
        )
        self.card("1", bank_employee=self.bank_sherzod)
        cases = (
            ("post", "/api/payroll/bank-employee-links/", {"bank_employee_id": foreign_bank.pk, "employee_id": self.alice.pk}),
            ("post", "/api/payroll/bank-employee-links/", {"bank_employee_id": self.bank_sherzod.pk, "employee_id": stranger.pk}),
            ("post", f"/api/payroll/card-payouts/{foreign_row.pk}/assign/", {"employee_id": self.alice.pk}),
            ("put", f"/api/payroll/documents/{foreign_doc.pk}/expected-card/", {"items": []}),
        )
        for method, url, body in cases:
            self.assertEqual(self.post(url, body, method=method).status_code, 404, (url, body))
        self.assertFalse(PayrollBankEmployeeLink.objects.exists())


class CardCommandTests(_SyncMixin, TestCase):
    def setUp(self):
        self.setup_sync()
        patcher = patch(
            "apps.modules.payroll.card_sync.KapitalbankClient",
            side_effect=lambda login, password: KapitalbankClient(login, password, session=self.bank),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, *args):
        out = StringIO()
        call_command("sync_payroll_card_payouts", *args, "--now", "2026-10-02T12:00:00+05:00", stdout=out)
        return out.getvalue()

    def test_manual_since_prints_counters_only(self):
        output = self.call("--mode", "manual", "--since", "2026-10-01")
        self.assertIn("payouts_created=5", output)
        self.assertEqual(PayrollCardPayout.objects.count(), 5)
        for secret in (*CARD_NAMES, *CARD_ACCOUNTS, *PII_MARKERS, TRANSIT_ACCOUNT):
            self.assertNotIn(secret, output)

    def test_dry_run_writes_nothing(self):
        output = self.call("--mode", "manual", "--since", "2026-10-01", "--dry-run")
        self.assertIn("(dry-run)", output)
        self.assertFalse(PayrollCardPayout.objects.exists())
        self.assertFalse(PayrollCardBatch.objects.exists())
        self.assertFalse(SyncEvent.objects.exists())

    def test_since_rules(self):
        with self.assertRaises(CommandError):
            self.call("--mode", "hourly", "--since", "2026-10-01")
        with self.assertRaises(CommandError):
            self.call("--mode", "manual")
        with self.assertRaises(CommandError):
            self.call("--mode", "manual", "--since", "2026-10-03")

    def test_crontab_runs_the_command(self):
        crontab = (Path(settings.BASE_DIR) / "cron" / "crontab").read_text()
        lines = [line for line in crontab.splitlines() if "sync_payroll_card_payouts" in line and not line.startswith("#")]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("flock -n /tmp/sync_payroll_card_payouts.lock", line)
        self.assertTrue(any("--mode hourly" in line for line in lines))
        self.assertTrue(any("--mode nightly" in line for line in lines))


ROLE_SQL = Path(__file__).resolve().parents[4] / "scripts" / "postgres_mcp_create_readonly_role.sql"


# The production container mounts only backend_v2/, so the script is checked in CI only.
@skipUnless(ROLE_SQL.exists(), "scripts/ is not available (backend_v2-only checkout)")
class McpHiddenTablesTest(SimpleTestCase):
    def test_card_tables_with_personal_data_are_hidden(self):
        # Criterion 22.
        block = ROLE_SQL.read_text().split("FROM (VALUES", 1)[1].split(") AS t(tbl)", 1)[0]
        hidden = set(re.findall(r"\('([a-z0-9_]+)'\)", block))
        for model in (BankPayrollEmployee, BankPayrollEmployeeAccount, PayrollCardBatch, PayrollCardPayout):
            self.assertIn(model._meta.db_table, hidden)
