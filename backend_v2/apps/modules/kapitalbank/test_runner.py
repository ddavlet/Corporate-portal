import base64
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.db import DEFAULT_DB_ALIAS, connections
from django.test import TestCase

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.cash_withdrawals.fixtures import GATEWAY_PATH, gateway_ok
from apps.modules.vendors.models import Vendor
from apps.modules.wallets.calendar_utils import TASHKENT, start_of_year_utc

from .client import BankListedAccount, KapitalbankError, Statement, StatementDoc
from .fixtures import ACCOUNT_1, ACCOUNT_2, MFO, KapitalbankFixtures
from .ingest import IngestResult
from .models import AccountSyncState, BankAccountLink, KapitalbankAlertSettings, KapitalbankConnection, SyncEvent
from .runner import LOCK_ID, NIGHTLY_DAYS_BACK, days_for, refresh_accounts, run

PASSWORD = "S3cret-bank-pass"
LOGIN = "IB#secretlogin"
PENDING_ACCOUNT = "20208000904843803009"
IGNORED_ACCOUNT = "20208000904843803010"
NEW_ACCOUNT = "20208000904843803011"
COUNTERPARTY = "20208840100400002020"
NOW = datetime(2026, 10, 26, 7, 0, tzinfo=dt_timezone.utc)  # 12:00 in Tashkent
TODAY = date(2026, 10, 26)
NIGHTLY_DAYS = [TODAY - timedelta(days=n) for n in range(NIGHTLY_DAYS_BACK, -1, -1)]
PAST_DAYS = NIGHTLY_DAYS[:-1]  # oldest first, as re-fetched by the self-heal
NIGHTLY_ORDER = [TODAY] + PAST_DAYS[::-1]  # nightly load order: today, then newest to oldest
BASIC_TOKEN = base64.b64encode(f"{LOGIN}:{PASSWORD}".encode()).decode()


def make_doc(n, *, day, incoming, account=ACCOUNT_1, counterparty=COUNTERPARTY, amount="1000.00"):
    ours = (MFO, account, "ООО Наша")
    theirs = ("00365", counterparty, "ООО Контрагент")
    dt, ct = (theirs, ours) if incoming else (ours, theirs)
    return StatementDoc(
        general_id=f"RUN{n}",
        b2_id=f"B{n}",
        num=f"{n:012d}",
        ddate=day,
        vdate=day,
        acc_dt=dt[1],
        acc_ct=ct[1],
        name_dt=dt[2],
        name_ct=ct[2],
        inn_dt="201122919",
        inn_ct="201122920",
        mfo_dt=dt[0],
        mfo_ct=ct[0],
        purpose=f"Оплата {n}",
        dtype="21",
        amount=Decimal(amount),
        state=1,
        dir=1 if incoming else 2,
    )


def statement(*docs, saldo_out="0.00"):
    return Statement(
        docs=list(docs),
        saldo_in=Decimal(0),
        saldo_out=None if saldo_out is None else Decimal(saldo_out),
        total_debit=Decimal(0),
        total_credit=Decimal(0),
        fin=True,
        oper_day=None,
    )


def listed(account_no):
    return BankListedAccount(
        account_no=account_no, branch=MFO, name="Счёт", currency="000", state_name="Открыт", balance=Decimal("1.00")
    )


class FakeClient:
    """statements[(account_no, day)] is a queue: each fetch pops one, the last one repeats."""

    def __init__(self):
        self.calls = []
        self.statements = {}
        self.errors = {}
        self.day_errors = {}
        self.accounts = []
        self.list_calls = 0
        self.list_error = None

    def get_statement(self, *, account_no, branch, day):
        self.calls.append((account_no, day))
        if account_no in self.errors:
            raise self.errors[account_no]
        if (account_no, day) in self.day_errors:
            raise self.day_errors[(account_no, day)]
        queue = self.statements.get((account_no, day))
        if not queue:
            return statement()
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def list_accounts(self):
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return self.accounts

    def days(self, account_no):
        return [day for acc, day in self.calls if acc == account_no]


class RunnerTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.conn = KapitalbankConnection(tenant=self.tenant, login=LOGIN, is_enabled=True)
        self.conn.set_password(PASSWORD)
        self.conn.save()
        alert_settings = KapitalbankAlertSettings.load()
        alert_settings.bot_tenant = self.tenant
        alert_settings.recipient = self.owner
        alert_settings.save()
        # …3004 is created first, so it is processed before …3001.
        self.link2 = BankAccountLink.objects.create(
            tenant=self.tenant, account_no=ACCOUNT_2, branch=MFO, name="Счёт 2",
            decision=BankAccountLink.LINKED, bank_account=self.bank_account2,
        )
        self.link1 = BankAccountLink.objects.create(
            tenant=self.tenant, account_no=ACCOUNT_1, branch=MFO, name="Счёт 1",
            decision=BankAccountLink.LINKED, bank_account=self.bank_account1,
        )
        BankAccountLink.objects.create(tenant=self.tenant, account_no=PENDING_ACCOUNT, branch=MFO)
        BankAccountLink.objects.create(
            tenant=self.tenant, account_no=IGNORED_ACCOUNT, branch=MFO,
            decision=BankAccountLink.IGNORED, ignore_reason="депозит",
        )
        self.fake = FakeClient()
        self.factory_calls = 0
        # Portal balance is "as of now" (wall clock); pin it to NOW so the tests are date-independent.
        patches = [
            patch("apps.modules.wallets.services.now_tashkent", lambda: NOW.astimezone(TASHKENT)),
            patch("apps.modules.wallets.services.ytd_bounds", lambda: (start_of_year_utc(2026), NOW, 2026)),
            patch(GATEWAY_PATH, side_effect=gateway_ok()),
        ]
        mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.gw = mocks[-1]

    def factory(self, conn):
        self.factory_calls += 1
        return self.fake

    def run_import(self, mode="daytime", **kwargs):
        kwargs.setdefault("now", NOW)
        return run(mode=mode, client_factory=self.factory, **kwargs)

    def texts(self):
        return [c.kwargs["payload"]["text"] for c in self.gw.call_args_list]

    def other_connection(self):
        other = connections.create_connection(DEFAULT_DB_ALIAS)
        self.addCleanup(other.close)
        return other

    # --- days and scope -------------------------------------------------------------------

    def test_days_for(self):
        self.assertEqual(days_for("daytime", TODAY), [TODAY])
        self.assertEqual(days_for("nightly", TODAY), NIGHTLY_DAYS)
        manual = [date(2026, 10, 20), date(2026, 10, 21)]
        self.assertEqual(days_for("manual", TODAY, manual), manual)
        with self.assertRaises(ValueError):
            days_for("manual", TODAY)

    def test_daytime_loads_today_only(self):
        report = self.run_import("daytime")

        self.assertEqual(self.fake.days(ACCOUNT_1), [TODAY])
        self.assertEqual(self.fake.days(ACCOUNT_2), [TODAY])
        self.assertEqual(self.fake.list_calls, 0)
        self.assertFalse(report.skipped_locked)
        self.assertEqual((report.accounts_ok, report.accounts_failed, report.alerts), (2, 0, 0))
        state = AccountSyncState.objects.get(link=self.link1)
        self.assertEqual(state.last_success_at, NOW)
        self.assertEqual(state.consecutive_failures, 0)
        self.gw.assert_not_called()

    def test_nightly_loads_six_days_and_refreshes_accounts(self):
        self.fake.accounts = [listed(ACCOUNT_1), listed(NEW_ACCOUNT)]

        report = self.run_import("nightly")

        self.assertEqual(self.fake.days(ACCOUNT_1), NIGHTLY_ORDER)
        self.assertEqual(self.fake.days(ACCOUNT_2), NIGHTLY_ORDER)
        self.assertEqual(self.fake.list_calls, 1)
        new = BankAccountLink.objects.get(tenant=self.tenant, account_no=NEW_ACCOUNT)
        self.assertEqual(new.decision, BankAccountLink.PENDING)
        self.link1.refresh_from_db()
        self.assertEqual(self.link1.decision, BankAccountLink.LINKED)
        self.assertEqual(report.accounts_ok, 2)
        self.gw.assert_not_called()

    def test_manual_loads_given_days(self):
        manual = [date(2026, 10, 1), date(2026, 10, 2)]
        self.run_import("manual", days=manual, tenant_subdomain="kp")
        self.assertEqual(self.fake.days(ACCOUNT_1), manual)
        self.assertEqual(self.fake.list_calls, 0)

    def test_only_linked_accounts_are_loaded(self):
        self.run_import("daytime")
        self.assertEqual({acc for acc, _ in self.fake.calls}, {ACCOUNT_1, ACCOUNT_2})

    def test_other_tenant_filter_loads_nothing(self):
        report = self.run_import("daytime", tenant_subdomain="other")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(report.accounts_ok, 0)

    # --- isolation and errors -------------------------------------------------------------

    def test_one_account_failure_does_not_stop_others(self):
        self.fake.statements[(ACCOUNT_1, TODAY)] = [
            statement(make_doc(1, day=TODAY, incoming=True), saldo_out="1000.00")
        ]
        self.fake.errors[ACCOUNT_2] = KapitalbankError(60102, "Счёт заблокирован")

        report = self.run_import("daytime")

        self.assertTrue(BankRevenue.objects.filter(external_id="RUN1", wallet=self.wallet1).exists())
        self.assertEqual((report.accounts_ok, report.accounts_failed, report.created), (1, 1, 1))
        state = AccountSyncState.objects.get(link=self.link2)
        self.assertEqual(state.last_error_code, 60102)
        self.assertEqual(state.last_error_message, "Счёт заблокирован")
        self.assertEqual(state.last_error_at, NOW)
        self.assertEqual(state.consecutive_failures, 1)
        self.assertIsNone(state.last_success_at)
        self.assertTrue(SyncEvent.objects.filter(link=self.link2, kind=SyncEvent.ERROR).exists())
        self.assertTrue(SyncEvent.objects.filter(link=self.link1, kind=SyncEvent.IMPORTED, day=TODAY).exists())
        self.assertEqual(AccountSyncState.objects.get(link=self.link1).last_success_at, NOW)
        # A single daytime failure is not "down" yet; …3001 balance matches.
        self.gw.assert_not_called()
        self.assertEqual(report.alerts, 0)

    def test_non_bank_error_is_isolated_without_code(self):
        self.fake.errors[ACCOUNT_2] = ValueError("bad saldo")

        report = self.run_import("daytime")

        self.assertEqual((report.accounts_ok, report.accounts_failed), (1, 1))
        state = AccountSyncState.objects.get(link=self.link2)
        self.assertIsNone(state.last_error_code)
        self.assertIn("ValueError", state.last_error_message)
        self.assertEqual(self.fake.days(ACCOUNT_1), [TODAY])

    def test_error_texts_never_contain_credentials(self):
        self.fake.errors[ACCOUNT_2] = RuntimeError(f"auth {LOGIN}:{PASSWORD} Basic {BASIC_TOKEN} rejected")

        with self.assertLogs("apps.modules.kapitalbank.runner", level="ERROR") as logs:
            self.run_import("nightly")  # nightly: the failure is alerted, so the alert text is checked too

        state = AccountSyncState.objects.get(link=self.link2)
        stored = [state.last_error_message, *SyncEvent.objects.values_list("message", flat=True)]
        stored += [str(p) for p in SyncEvent.objects.values_list("payload", flat=True)]
        stored += self.texts()
        stored += logs.output
        self.assertTrue(self.texts())
        self.assertTrue(any("RuntimeError" in line for line in logs.output))
        for text in stored:
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn("secretlogin", text)
            self.assertNotIn(BASIC_TOKEN, text)

    def test_missing_password_is_config_error(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(password_enc="not-a-fernet-token")

        report = self.run_import("daytime")

        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(report.accounts_failed, 2)
        event = SyncEvent.objects.get(kind=SyncEvent.ERROR)
        self.assertIsNone(event.link)
        self.assertEqual(event.tenant, self.tenant)
        self.assertNotIn("secretlogin", event.message)

    def test_missing_password_reaches_accounts_and_owner(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(password_enc="")

        self.run_import("daytime")
        report = self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.assertEqual(self.fake.calls, [])
        state = AccountSyncState.objects.get(link=self.link1)
        self.assertEqual(state.consecutive_failures, 2)
        self.assertEqual(state.last_error_at, NOW + timedelta(minutes=10))
        self.assertIsNone(state.last_error_code)
        self.assertIn("Пароль банка", state.last_error_message)
        # second failure without any success → down alert for each linked account
        self.assertEqual(self.gw.call_count, 2)
        self.assertEqual(report.alerts, 2)
        self.assertIn("не работает", self.texts()[0])
        # one tenant-level event per day and cause, not one per run
        self.assertEqual(SyncEvent.objects.filter(kind=SyncEvent.ERROR, link=None).count(), 1)

    def test_dry_run_with_missing_password_writes_nothing(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(password_enc="")

        report = self.run_import("nightly", dry_run=True)

        self.assertEqual(report.accounts_failed, 2)
        self.assertEqual(SyncEvent.objects.count(), 0)
        self.assertEqual(AccountSyncState.objects.count(), 0)
        self.gw.assert_not_called()

    def test_client_factory_failure_reaches_accounts(self):
        def broken_factory(conn):
            raise RuntimeError(f"cannot build client for {LOGIN}")

        run(mode="nightly", now=NOW, client_factory=broken_factory)

        state = AccountSyncState.objects.get(link=self.link2)
        self.assertEqual(state.consecutive_failures, 1)
        self.assertNotIn("secretlogin", state.last_error_message)
        event = SyncEvent.objects.get(kind=SyncEvent.ERROR, link=None)
        self.assertNotIn("secretlogin", event.message)
        self.assertEqual(self.gw.call_count, 2)  # nightly failure → down alert per account

    def test_tenant_level_exception_is_recorded_once_per_day(self):
        with patch("apps.modules.kapitalbank.runner._own_targets", side_effect=RuntimeError("db hiccup")):
            first = self.run_import("daytime")
            self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.assertEqual(first.accounts_failed, 2)
        self.assertEqual(self.fake.calls, [])
        events = SyncEvent.objects.filter(kind=SyncEvent.ERROR, link=None)
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.get().payload["stage"], "tenant")
        self.assertEqual(AccountSyncState.objects.get(link=self.link1).consecutive_failures, 2)

    def test_bad_past_day_does_not_block_today(self):
        self.fake.day_errors[(ACCOUNT_1, TODAY - timedelta(days=2))] = KapitalbankError(None, "HTTP 502")
        self.fake.statements[(ACCOUNT_1, TODAY)] = [
            statement(make_doc(1, day=TODAY, incoming=True), saldo_out="1000.00")
        ]

        report = self.run_import("nightly")

        self.assertEqual(self.fake.days(ACCOUNT_1), NIGHTLY_ORDER)  # today first, all days tried
        self.assertTrue(BankRevenue.objects.filter(external_id="RUN1", wallet=self.wallet1).exists())
        self.assertEqual((report.accounts_ok, report.accounts_failed), (1, 1))
        state = AccountSyncState.objects.get(link=self.link1)
        self.assertEqual(state.consecutive_failures, 1)
        self.assertIsNone(state.last_success_at)
        self.assertTrue(
            SyncEvent.objects.filter(link=self.link1, kind=SyncEvent.ERROR, day=TODAY - timedelta(days=2)).exists()
        )
        # balance matched; the only message is the nightly down alert
        self.assertEqual(self.gw.call_count, 1)
        self.assertIn("не работает", self.texts()[0])

    def test_account_list_failure_still_loads_statements(self):
        self.fake.list_error = KapitalbankError(None, "HTTP 503")

        report = self.run_import("nightly")

        self.assertTrue(SyncEvent.objects.filter(kind=SyncEvent.ERROR, link=None, tenant=self.tenant).exists())
        self.assertEqual(self.fake.days(ACCOUNT_1), NIGHTLY_ORDER)
        self.assertEqual(report.accounts_ok, 2)

    def test_alert_failure_does_not_fail_run(self):
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(saldo_out="1000.00")]
        with patch("apps.modules.kapitalbank.alerts.notify_mismatch", side_effect=RuntimeError("boom")):
            report = self.run_import("daytime")
        self.assertEqual((report.accounts_ok, report.accounts_failed, report.alerts), (2, 0, 0))
        self.assertEqual(AccountSyncState.objects.get(link=self.link1).last_success_at, NOW)

    def test_missing_docs_are_alerted(self):
        missing = IngestResult(missing_external_ids=["X1"])
        with patch("apps.modules.kapitalbank.runner.ingest_statement", return_value=missing):
            report = self.run_import("daytime", tenant_subdomain="kp")
        self.assertEqual(self.gw.call_count, 2)  # one per account
        self.assertIn("Документы пропали", self.texts()[0])
        self.assertEqual(report.alerts, 2)

    # --- balance reconciliation -----------------------------------------------------------

    def test_past_day_load_does_not_alert_balance(self):
        for day in PAST_DAYS:
            self.fake.statements[(ACCOUNT_1, day)] = [statement(saldo_out="999999.00")]

        self.run_import("nightly")

        self.gw.assert_not_called()
        self.assertEqual(self.fake.days(ACCOUNT_1), NIGHTLY_ORDER)  # no re-fetch

    def test_mismatch_self_heals_before_alert(self):
        late_day = TODAY - timedelta(days=3)
        late = make_doc(1, day=late_day, incoming=True, amount="1000.00")
        self.fake.statements[(ACCOUNT_1, late_day)] = [statement(), statement(late)]
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(saldo_out="1000.00")]

        report = self.run_import("nightly")

        self.gw.assert_not_called()
        self.assertTrue(BankRevenue.objects.filter(external_id="RUN1", wallet=self.wallet1).exists())
        self.assertEqual(self.fake.days(ACCOUNT_1), NIGHTLY_ORDER + PAST_DAYS + [TODAY])
        self.assertEqual((report.created, report.alerts), (1, 0))
        self.assertIsNone(AccountSyncState.objects.get(link=self.link1).mismatch_alerted_at)

    def test_persistent_mismatch_alerts_once(self):
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(saldo_out="1000.00")]

        first = self.run_import("daytime")
        second = self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.assertEqual(self.gw.call_count, 1)
        self.assertEqual((first.alerts, second.alerts), (1, 0))
        self.assertIn("Расхождение остатка", self.texts()[0])
        self.assertIn("1 000,00", self.texts()[0])
        state = AccountSyncState.objects.get(link=self.link1)
        self.assertEqual(state.mismatch_bank, Decimal("1000.00"))
        self.assertEqual(state.mismatch_portal, Decimal("0.00"))
        self.assertEqual(state.mismatch_alerted_at, NOW)

    def test_balance_checked_on_empty_statement(self):
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(saldo_out="500.00")]

        self.run_import("daytime")

        self.assertEqual(self.fake.days(ACCOUNT_1), [TODAY] + PAST_DAYS + [TODAY])
        self.assertEqual(self.gw.call_count, 1)
        self.assertIn("Расхождение остатка", self.texts()[0])

    def test_missing_saldo_out_skips_reconcile(self):
        AccountSyncState.objects.create(
            link=self.link1, mismatch_since=NOW - timedelta(hours=1), mismatch_alerted_at=NOW - timedelta(hours=1)
        )
        self.fake.statements[(ACCOUNT_1, TODAY)] = [
            statement(make_doc(1, day=TODAY, incoming=True), saldo_out=None)
        ]

        with self.assertLogs("apps.modules.kapitalbank.runner", level="WARNING") as logs:
            report = self.run_import("daytime")

        self.gw.assert_not_called()  # neither mismatch (portal 1000 vs nothing) nor resolved
        self.assertEqual(self.fake.days(ACCOUNT_1), [TODAY])  # no self-heal re-fetch
        self.assertTrue(any("saldo_out" in line for line in logs.output))
        detail = [d for d in report.details if d["account_no"] == ACCOUNT_1][0]
        self.assertIsNone(detail["saldo_out"])
        self.assertIn("skipped", detail["reconcile"])
        self.assertIsNotNone(AccountSyncState.objects.get(link=self.link1).mismatch_alerted_at)
        self.assertEqual(report.accounts_ok, 2)

    def test_resolved_after_alerted_mismatch(self):
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(saldo_out="1000.00")]
        self.run_import("daytime")
        self.fake.statements[(ACCOUNT_1, TODAY)] = [
            statement(make_doc(1, day=TODAY, incoming=True), saldo_out="1000.00")
        ]

        report = self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.assertEqual(self.gw.call_count, 2)
        self.assertEqual(report.alerts, 1)
        self.assertIn("сошёлся", self.texts()[1])
        self.assertIsNone(AccountSyncState.objects.get(link=self.link1).mismatch_alerted_at)

    # --- own transfers --------------------------------------------------------------------

    def test_transfer_to_untracked_own_account_alerts(self):
        to_pending = make_doc(1, day=TODAY, incoming=False, counterparty=PENDING_ACCOUNT, amount="300.00")
        to_linked = make_doc(2, day=TODAY, incoming=False, counterparty=ACCOUNT_2, amount="200.00")
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(to_pending, to_linked, saldo_out="-500.00")]

        first = self.run_import("daytime")
        second = self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.assertEqual(self.gw.call_count, 1)
        self.assertEqual((first.alerts, second.alerts), (1, 0))
        self.assertIn("Перевод на свой счёт", self.texts()[0])
        self.assertIn(PENDING_ACCOUNT, self.texts()[0])
        self.assertEqual(BankExpense.objects.filter(wallet=self.wallet1).count(), 2)

    def test_transfer_to_ignored_own_account_alerts(self):
        doc = make_doc(1, day=TODAY, incoming=False, counterparty=IGNORED_ACCOUNT, amount="300.00")
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(doc, saldo_out="-300.00")]

        self.run_import("daytime")

        self.assertEqual(self.gw.call_count, 1)
        self.assertIn(IGNORED_ACCOUNT, self.texts()[0])

    def test_own_transfer_only_for_new_documents(self):
        doc = make_doc(1, day=TODAY, incoming=False, counterparty=NEW_ACCOUNT, amount="300.00")
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(doc, saldo_out="-300.00")]
        self.run_import("daytime")  # NEW_ACCOUNT unknown yet: imported, no alert
        BankAccountLink.objects.create(tenant=self.tenant, account_no=NEW_ACCOUNT, branch=MFO)

        self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.gw.assert_not_called()

    # --- down alerts ----------------------------------------------------------------------

    def test_down_alert_after_an_hour_without_success(self):
        AccountSyncState.objects.create(
            link=self.link2, last_success_at=NOW - timedelta(minutes=61), consecutive_failures=1
        )
        self.fake.errors[ACCOUNT_2] = KapitalbankError(None, "HTTP 502")

        report = self.run_import("daytime")

        self.assertEqual(self.gw.call_count, 1)
        self.assertIn("не работает", self.texts()[0])
        self.assertIn("HTTP 502", self.texts()[0])
        self.assertEqual(report.alerts, 1)

    def test_no_down_alert_within_an_hour(self):
        AccountSyncState.objects.create(
            link=self.link2, last_success_at=NOW - timedelta(minutes=30), consecutive_failures=5
        )
        self.fake.errors[ACCOUNT_2] = KapitalbankError(None, "HTTP 502")

        self.run_import("daytime")

        self.gw.assert_not_called()
        self.assertEqual(AccountSyncState.objects.get(link=self.link2).consecutive_failures, 6)

    def test_single_daytime_failure_does_not_alert_down(self):
        # e.g. the first daytime run after the 05:00 success fails once at 06:10
        AccountSyncState.objects.create(link=self.link2, last_success_at=NOW - timedelta(hours=7))
        self.fake.errors[ACCOUNT_2] = KapitalbankError(None, "HTTP 502")

        self.run_import("daytime")

        self.gw.assert_not_called()
        self.assertEqual(AccountSyncState.objects.get(link=self.link2).consecutive_failures, 1)

        self.run_import("daytime", now=NOW + timedelta(minutes=10))

        self.assertEqual(self.gw.call_count, 1)
        self.assertIn("не работает", self.texts()[0])

    def test_nightly_failure_alerts_down_even_after_recent_success(self):
        AccountSyncState.objects.create(link=self.link2, last_success_at=NOW - timedelta(minutes=10))
        self.fake.errors[ACCOUNT_2] = KapitalbankError(None, "HTTP 502")

        self.run_import("nightly")

        self.assertEqual(self.gw.call_count, 1)
        self.assertIn("не работает", self.texts()[0])

    # --- lock and dry run -----------------------------------------------------------------

    def test_concurrent_run_is_skipped(self):
        other = self.other_connection()
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [LOCK_ID])
        try:
            report = self.run_import("daytime")
        finally:
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])

        self.assertTrue(report.skipped_locked)
        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(self.fake.calls, [])

    def test_lock_released_after_run(self):
        self.fake.errors[ACCOUNT_2] = ValueError("boom")
        self.run_import("daytime")

        other = self.other_connection()
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            acquired = cursor.fetchone()[0]
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
        self.assertTrue(acquired)

    def test_lock_released_when_run_raises(self):
        with patch("apps.modules.kapitalbank.runner._enabled_connections", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_import("daytime")

        other = self.other_connection()
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            acquired = cursor.fetchone()[0]
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
        self.assertTrue(acquired)

    def test_dry_run_writes_nothing(self):
        self.fake.accounts = [listed(NEW_ACCOUNT)]
        self.fake.statements[(ACCOUNT_1, TODAY)] = [
            statement(
                make_doc(1, day=TODAY, incoming=True),
                make_doc(2, day=TODAY, incoming=False, counterparty=PENDING_ACCOUNT),
                saldo_out="77.00",
            )
        ]
        self.fake.errors[ACCOUNT_2] = KapitalbankError(60102, "x")
        links_before = BankAccountLink.objects.count()

        report = self.run_import("nightly", dry_run=True)

        self.assertEqual(BankRevenue.objects.count(), 0)
        self.assertEqual(BankExpense.objects.count(), 0)
        self.assertFalse(Vendor.objects.filter(tenant=self.tenant).exists())
        self.assertEqual(SyncEvent.objects.count(), 0)
        self.assertEqual(AccountSyncState.objects.count(), 0)
        self.assertEqual(BankAccountLink.objects.count(), links_before)
        self.assertEqual(self.fake.list_calls, 0)
        self.gw.assert_not_called()
        self.assertEqual((report.accounts_ok, report.accounts_failed, report.alerts), (1, 1, 0))
        today_detail = [d for d in report.details if d["account_no"] == ACCOUNT_1 and d["day"] == TODAY.isoformat()]
        self.assertEqual(len(today_detail), 1)
        self.assertEqual(len(today_detail[0]["would_create"]), 2)
        self.assertEqual(today_detail[0]["portal_balance"], "0.00")

    # --- transfers between linked accounts ------------------------------------------------

    def test_transfer_between_two_linked_accounts_imports_both_sides(self):
        # …3004 -> …3001, both LINKED: expense on …3004, revenue on …3001, balances match.
        transfer = make_doc(7, day=TODAY, incoming=False, account=ACCOUNT_2, counterparty=ACCOUNT_1, amount="1000.00")
        self.fake.statements[(ACCOUNT_2, TODAY)] = [statement(transfer, saldo_out="-1000.00")]
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(transfer, saldo_out="1000.00")]

        report = self.run_import("daytime")

        self.assertEqual(BankExpense.objects.get(external_id="RUN7").wallet, self.wallet2)
        self.assertEqual(BankRevenue.objects.get(external_id="RUN7").wallet, self.wallet1)
        self.assertEqual((report.accounts_ok, report.accounts_failed, report.created, report.alerts), (2, 0, 2, 0))
        self.gw.assert_not_called()  # no missing-docs, no mismatch, no own-transfer alert
        self.assertFalse(SyncEvent.objects.filter(kind=SyncEvent.MISSING_DOCS).exists())
        for detail in report.details:
            self.assertEqual(detail["missing_external_ids"], [])
            self.assertEqual(detail["reconcile"], "match")
        self.assertEqual(self.fake.days(ACCOUNT_1), [TODAY])  # no self-heal re-fetch needed

    # --- cutover: dry run before enabling, account list refresh ---------------------------

    def test_dry_run_for_named_tenant_ignores_is_enabled(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(is_enabled=False)
        self.fake.statements[(ACCOUNT_1, TODAY)] = [statement(make_doc(1, day=TODAY, incoming=True), saldo_out="1000.00")]

        report = self.run_import("daytime", dry_run=True, tenant_subdomain="kp")

        self.assertEqual({acc for acc, _ in self.fake.calls}, {ACCOUNT_1, ACCOUNT_2})  # LINKED only
        self.assertEqual(report.accounts_ok, 2)
        detail = [d for d in report.details if d["account_no"] == ACCOUNT_1][0]
        self.assertEqual([i["external_id"] for i in detail["would_create"]], ["RUN1"])
        self.assertEqual(BankRevenue.objects.count(), 0)
        self.assertEqual(SyncEvent.objects.count(), 0)
        self.assertEqual(AccountSyncState.objects.count(), 0)
        self.gw.assert_not_called()

    def test_disabled_tenant_is_not_loaded_without_dry_run_or_tenant(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(is_enabled=False)

        self.run_import("daytime", tenant_subdomain="kp")
        self.run_import("daytime", dry_run=True)

        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.factory_calls, 0)

    def test_dry_run_disabled_tenant_without_password_fails_cleanly(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(is_enabled=False, password_enc="")

        report = self.run_import("daytime", dry_run=True, tenant_subdomain="kp")

        self.assertEqual(self.factory_calls, 0)
        self.assertEqual(report.accounts_failed, 2)
        self.assertEqual(SyncEvent.objects.count(), 0)

    def test_refresh_accounts_works_while_disabled_and_writes_links_only(self):
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(is_enabled=False)
        self.fake.accounts = [listed(ACCOUNT_1), listed(NEW_ACCOUNT)]

        report = refresh_accounts(tenant_subdomain="kp", now=NOW, client_factory=self.factory)

        self.assertEqual(report.error, "")
        self.assertEqual([link.account_no for link in report.links], [ACCOUNT_1, NEW_ACCOUNT])
        self.assertEqual(self.fake.list_calls, 1)
        self.assertEqual(self.fake.calls, [])  # no statements
        new = BankAccountLink.objects.get(tenant=self.tenant, account_no=NEW_ACCOUNT)
        self.assertEqual(new.decision, BankAccountLink.PENDING)
        self.assertEqual(new.currency, "UZS")
        self.link1.refresh_from_db()
        self.assertEqual(self.link1.decision, BankAccountLink.LINKED)
        self.assertEqual(self.link1.bank_account_id, self.bank_account1.pk)
        self.assertEqual(SyncEvent.objects.count(), 0)
        self.assertEqual(AccountSyncState.objects.count(), 0)
        self.assertEqual(BankRevenue.objects.count() + BankExpense.objects.count(), 0)
        self.gw.assert_not_called()
        other = self.other_connection()
        with other.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_ID])
            acquired = cursor.fetchone()[0]
            cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
        self.assertTrue(acquired)

    def test_refresh_accounts_errors_are_redacted(self):
        self.fake.list_error = RuntimeError(f"auth {LOGIN}:{PASSWORD} rejected")

        with self.assertLogs("apps.modules.kapitalbank.runner", level="ERROR") as logs:
            report = refresh_accounts(tenant_subdomain="kp", now=NOW, client_factory=self.factory)

        self.assertIn("Не удалось обновить список счетов", report.error)
        for text in [report.error, *logs.output]:
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn("secretlogin", text)
        self.assertEqual(refresh_accounts(tenant_subdomain="nope", now=NOW, client_factory=self.factory).links, [])
        KapitalbankConnection.objects.filter(pk=self.conn.pk).update(password_enc="")
        no_password = refresh_accounts(tenant_subdomain="kp", now=NOW, client_factory=self.factory)
        self.assertIn("Пароль", no_password.error)
        self.assertEqual(self.factory_calls, 1)

    # --- nightly account list failure reaches the owner ----------------------------------

    def test_nightly_account_list_failure_alerts_owner_once_per_day(self):
        self.fake.list_error = KapitalbankError(None, f"HTTP 503 for {LOGIN}:{PASSWORD}")

        first = self.run_import("nightly")
        second = self.run_import("nightly", now=NOW + timedelta(minutes=10))

        self.assertEqual(self.gw.call_count, 1)
        self.assertEqual((first.alerts, second.alerts), (1, 0))
        text = self.texts()[0]
        self.assertIn("Список счетов", text)
        self.assertIn("HTTP 503", text)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn("secretlogin", text)
        event = SyncEvent.objects.get(dedup_key=f"accounts_refresh:{self.tenant.pk}:{TODAY.isoformat()}")
        self.assertNotIn(PASSWORD, event.message)
        self.assertEqual(self.fake.days(ACCOUNT_1), NIGHTLY_ORDER * 2)  # statements still loaded on both runs
