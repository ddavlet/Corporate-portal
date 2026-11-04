import base64
from datetime import date
from decimal import Decimal
from unittest import mock

import requests
from django.test import SimpleTestCase

from apps.modules.kapitalbank.client import NETWORK_RETRIES, KapitalbankClient, KapitalbankError
from apps.modules.kapitalbank.fixtures import ACCOUNT_1, ACCOUNT_2, APILOGIN_JSON, MFO, STATEMENT_JSON


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
