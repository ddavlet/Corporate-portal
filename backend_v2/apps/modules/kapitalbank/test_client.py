import base64
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from unittest import mock

import requests
from django.test import SimpleTestCase

from apps.modules.kapitalbank.client import NETWORK_RETRIES, KapitalbankClient, KapitalbankError, mask_card
from apps.modules.kapitalbank.fixtures import (
    ACCOUNT_1,
    ACCOUNT_2,
    APILOGIN_JSON,
    APILOGIN_WITH_ZP_JSON,
    CARD_ACCOUNTS,
    CARD_NAMES,
    MFO,
    PAYROLL_CLIENT_ID,
    PII_MARKERS,
    STATEMENT_JSON,
    TRANSIT_ACCOUNT,
    WORKERS_JSON,
    ZP_JSON,
)


def _resp(payload, status=200):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = payload
    return r


def _client(session, login="IB#user", password="secret"):
    return KapitalbankClient(login, password, session=session)


class KapitalbankClientTests(SimpleTestCase):
    def test_get_statement_parses_tiyin_and_dates(self):
        session = mock.Mock()
        session.post.return_value = _resp(STATEMENT_JSON)
        st = _client(session).get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
        self.assertEqual(st.saldo_out, Decimal("460000.00"))
        self.assertEqual(st.docs[0].amount, Decimal("50000.00"))
        self.assertEqual(st.docs[0].ddate, date(2026, 2, 24))
        self.assertIs(st.fin, True)
        self.assertEqual(st.oper_day, date(2026, 2, 24))
        _, kwargs = session.post.call_args
        self.assertEqual(kwargs["json"], {"branch": MFO, "account": ACCOUNT_1, "date": "24.02.2026"})
        self.assertTrue(session.post.call_args[0][0].endswith("/GetDoc1C"))

    def test_missing_or_null_saldo_out_is_none(self):
        session = mock.Mock()
        for result in ({"content": [], "saldo_in": 0}, {"content": [], "saldo_in": 0, "saldo_out": None}):
            session.post.return_value = _resp({"error": None, "result": result})
            st = _client(session).get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
            self.assertIsNone(st.saldo_out)
        session.post.return_value = _resp({"error": None, "result": {"content": [], "saldo_out": 0}})
        st = _client(session).get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
        self.assertEqual(st.saldo_out, Decimal("0.00"))

    def test_basic_auth_header_and_no_secret_in_errors(self):
        session = mock.Mock()
        session.post.return_value = _resp({"error": {"code": 61002, "message": "IP"}, "result": None})
        client = _client(session, login="IB#user", password="p:a@ss Ж")
        with self.assertRaises(KapitalbankError) as ctx:
            client.get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
        expected = "Basic " + base64.b64encode("IB#user:p:a@ss Ж".encode()).decode()
        self.assertEqual(session.post.call_args[1]["headers"]["Authorization"], expected)
        self.assertEqual(session.post.call_args[1]["headers"]["Content-Type"], "application/json")
        self.assertEqual(ctx.exception.code, 61002)
        self.assertNotIn("p:a@ss", str(ctx.exception))
        self.assertNotIn("IB#user", str(ctx.exception))

    def test_retries_network_errors_then_raises(self):
        session = mock.Mock()
        session.post.side_effect = requests.ConnectionError("boom")
        with self.assertRaises(KapitalbankError):
            _client(session).get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
        self.assertEqual(session.post.call_count, NETWORK_RETRIES + 1)

    def test_api_error_is_not_retried(self):
        session = mock.Mock()
        session.post.return_value = _resp({"error": {"code": 60101, "message": "Сессия истекла"}})
        with self.assertRaises(KapitalbankError) as ctx:
            _client(session).get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
        self.assertEqual(ctx.exception.code, 60101)
        self.assertEqual(session.post.call_count, 1)

    def test_http_5xx_retried_and_4xx_not(self):
        session = mock.Mock()
        session.post.side_effect = [_resp({}, 502), _resp(STATEMENT_JSON)]
        st = _client(session).get_statement(account_no=ACCOUNT_1, branch=MFO, day=date(2026, 2, 24))
        self.assertEqual(len(st.docs), 2)
        session = mock.Mock()
        session.post.return_value = _resp({}, 403)
        with self.assertRaises(KapitalbankError) as ctx:
            _client(session).list_accounts()
        self.assertEqual(ctx.exception.message, "HTTP 403")
        self.assertIsNone(ctx.exception.code)
        self.assertEqual(session.post.call_count, 1)

    def test_list_accounts_flattens_all_clients(self):
        session = mock.Mock()
        session.post.return_value = _resp(APILOGIN_JSON)
        accounts = _client(session).list_accounts()
        self.assertEqual([a.account_no for a in accounts], [ACCOUNT_1, ACCOUNT_2])
        self.assertEqual(accounts[0].balance, Decimal("460000.00"))
        self.assertEqual(accounts[1].balance, Decimal("123.45"))
        self.assertEqual(accounts[0].currency, "000")
        self.assertEqual(accounts[0].state_name, "Открыт")
        self.assertTrue(session.post.call_args[0][0].endswith("/APILogin"))

    def test_list_accounts_pads_numeric_branch_and_currency(self):
        # The real APILogin returns branch and val as numbers: 1158 and 0.
        account = {**APILOGIN_JSON["result"]["clients"][0]["accounts"][0], "branch": 1158, "val": 0}
        usd = {**account, "account": ACCOUNT_2, "val": 840}
        payload = {**APILOGIN_JSON, "result": {**APILOGIN_JSON["result"], "clients": [{"accounts": [account, usd]}]}}
        session = mock.Mock()
        session.post.return_value = _resp(payload)
        accounts = _client(session).list_accounts()
        self.assertEqual([(a.branch, a.currency) for a in accounts], [(MFO, "000"), (MFO, "840")])


class KapitalbankPayrollDirectoryTests(SimpleTestCase):
    def _session(self, payload):
        session = mock.Mock()
        session.post.return_value = _resp(payload)
        return session

    def test_list_clients_parses_client_id_and_payroll_accounts(self):
        session = self._session(APILOGIN_WITH_ZP_JSON)
        clients = _client(session).list_clients()
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].client_id, str(PAYROLL_CLIENT_ID))
        self.assertEqual(clients[0].branch, MFO)
        self.assertEqual(clients[0].payroll_accounts, ((TRANSIT_ACCOUNT, MFO),))
        self.assertTrue(session.post.call_args[0][0].endswith("/APILogin"))

    def test_list_clients_without_payroll_accounts(self):
        clients = _client(self._session(APILOGIN_JSON)).list_clients()
        self.assertEqual([c.payroll_accounts for c in clients], [(), ()])

    def test_list_payroll_workers_keeps_only_whitelisted_fields(self):
        session = self._session(WORKERS_JSON)
        workers = _client(session).list_payroll_workers(client_id=str(PAYROLL_CLIENT_ID))
        self.assertEqual(session.post.call_args[1]["json"], {"client_id": PAYROLL_CLIENT_ID})
        self.assertTrue(session.post.call_args[0][0].endswith("/GetWorkers1C"))
        self.assertEqual([w.employee_id for w in workers], ["E1001", "E1002", "E1003"])
        self.assertEqual(workers[0].account_no, CARD_ACCOUNTS[0])
        self.assertEqual(workers[0].full_name, CARD_NAMES[0])
        self.assertEqual(workers[0].masked_card, "8600********0001")
        self.assertEqual(workers[0].branch, MFO)
        # A full card number from the bank is masked while parsing.
        self.assertEqual(workers[2].masked_card, "5614********0003")
        for worker in workers:
            text = f"{asdict(worker)!r} {worker!r}"
            for marker in PII_MARKERS:
                self.assertNotIn(marker, text)
            self.assertEqual(set(asdict(worker)), {"employee_id", "account_no", "full_name", "masked_card", "branch"})

    def test_get_payroll_sheets_flattens_rows_and_converts_tiyin(self):
        session = self._session(ZP_JSON)
        rows = _client(session).get_payroll_sheets(client_id=str(PAYROLL_CLIENT_ID), day=date(2026, 10, 2))
        self.assertEqual(session.post.call_args[1]["json"], {"client_id": PAYROLL_CLIENT_ID, "date": "02.10.2026"})
        self.assertTrue(session.post.call_args[0][0].endswith("/GetZP1C"))
        self.assertEqual([(r.employee_id, r.account_no) for r in rows], [("E1004", CARD_ACCOUNTS[3]), ("E1001", CARD_ACCOUNTS[0])])
        self.assertEqual(rows[0].amount, Decimal("2808000.00"))
        self.assertEqual(rows[0].sheet_date, date(2026, 10, 2))
        self.assertEqual(rows[0].sheet_name, "Ведомость №8 (02.10.2026)")

    def test_payroll_sheet_date_with_time_or_garbage(self):
        sheet = {**ZP_JSON["result"][0], "date_oper": "02.10.2026 10:15:00"}
        rows = _client(self._session({"error": None, "result": [sheet]})).get_payroll_sheets(client_id="1", day=date(2026, 10, 2))
        self.assertEqual(rows[0].sheet_date, date(2026, 10, 2))
        sheet = {**ZP_JSON["result"][0], "date_oper": "n/a"}
        rows = _client(self._session({"error": None, "result": [sheet]})).get_payroll_sheets(client_id="1", day=date(2026, 10, 2))
        self.assertIsNone(rows[0].sheet_date)

    def test_empty_or_unexpected_result_gives_empty_list(self):
        for payload in ({"error": None, "result": None}, {"error": None, "result": {"x": 1}}, {"error": None}):
            self.assertEqual(_client(self._session(payload)).list_payroll_workers(client_id="1"), [])
            self.assertEqual(_client(self._session(payload)).get_payroll_sheets(client_id="1", day=date(2026, 10, 2)), [])

    def test_mask_card(self):
        self.assertEqual(mask_card("8600 1234 5678 9012"), "8600********9012")
        self.assertEqual(mask_card("8600********9012"), "8600********9012")
        self.assertEqual(mask_card(None), "")
        self.assertEqual(mask_card("12345"), "")

    def test_bank_error_has_no_secret_and_logs_no_personal_data(self):
        session = mock.Mock()
        session.post.return_value = _resp({"error": {"code": 61002, "message": "IP"}, "result": None})
        client = _client(session, login="IB#user", password="p:a@ss")
        with self.assertLogs("apps.modules.kapitalbank.client", level="WARNING") as logs:
            with self.assertRaises(KapitalbankError) as ctx:
                client.list_payroll_workers(client_id=str(PAYROLL_CLIENT_ID))
        self.assertEqual(ctx.exception.code, 61002)
        text = str(ctx.exception) + "\n".join(logs.output)
        for secret in ("p:a@ss", "IB#user", *PII_MARKERS, *CARD_NAMES):
            self.assertNotIn(secret, text)

    def test_successful_parse_logs_nothing(self):
        with self.assertNoLogs("apps.modules.kapitalbank.client", level="DEBUG"):
            _client(self._session(WORKERS_JSON)).list_payroll_workers(client_id="1")
            _client(self._session(ZP_JSON)).get_payroll_sheets(client_id="1", day=date(2026, 10, 2))
