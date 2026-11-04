"""Kapitalbank (KapitalAPI V3) HTTP client: GetDoc1C statements and APILogin account list."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://m.bank24.uz:2713/Mobile.svc"
TIMEOUT_SECONDS = 30
NETWORK_RETRIES = 2

_TIYIN = Decimal(100)
_CENTS = Decimal("0.01")


class KapitalbankError(Exception):
    """Bank/API failure. Never carries credentials."""

    def __init__(self, code: int | None, message: str):
        self.code = code
        self.message = message
        super().__init__(f"Kapitalbank error {code}: {message}" if code is not None else message)


@dataclass(frozen=True)
class StatementDoc:
    general_id: str
    b2_id: str
    num: str
    ddate: date
    vdate: date
    acc_dt: str
    acc_ct: str
    name_dt: str
    name_ct: str
    inn_dt: str
    inn_ct: str
    mfo_dt: str
    mfo_ct: str
    purpose: str
    dtype: str
    amount: Decimal
    state: int
    dir: int


@dataclass(frozen=True)
class Statement:
    docs: list[StatementDoc]
    saldo_in: Decimal
    saldo_out: Decimal | None  # None when the bank omits it or sends null: never compare as 0
    total_debit: Decimal
    total_credit: Decimal
    fin: bool
    oper_day: date | None


@dataclass(frozen=True)
class BankListedAccount:
    account_no: str
    branch: str
    name: str
    currency: str
    state_name: str
    balance: Decimal


def _money(tiyin) -> Decimal:
    return (Decimal(int(tiyin or 0)) / _TIYIN).quantize(_CENTS)


def _parse_date(value) -> date | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%d.%m.%Y").date()


def _s(value) -> str:
    return "" if value is None else str(value)


def _code(value, width: int) -> str:
    """APILogin returns branch (МФО) and currency as numbers (1158, 0); restore the leading zeros
    ("01158", "000") the statement API, n8n and the portal accounts use."""
    raw = _s(value).strip()
    return raw.zfill(width) if raw.isdigit() else raw


class KapitalbankClient:
    def __init__(self, login: str, password: str, *, session: requests.Session | None = None):
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        self._headers = {"Content-Type": "application/json", "Authorization": f"Basic {token}"}
        self._session = session or requests.Session()

    def _call(self, method: str, body: dict, *, log_ctx: str = "") -> dict:
        url = f"{BASE_URL}/{method}"
        last: KapitalbankError | None = None
        for attempt in range(NETWORK_RETRIES + 1):
            try:
                resp = self._session.post(url, json=body, headers=self._headers, timeout=TIMEOUT_SECONDS)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last = KapitalbankError(None, f"Network error: {type(exc).__name__}")
                logger.warning("kapitalbank %s %s network error (attempt %s)", method, log_ctx, attempt + 1)
                continue
            status = resp.status_code
            if status >= 500:
                last = KapitalbankError(None, f"HTTP {status}")
                logger.warning("kapitalbank %s %s HTTP %s (attempt %s)", method, log_ctx, status, attempt + 1)
                continue
            if status >= 400:
                logger.warning("kapitalbank %s %s HTTP %s", method, log_ctx, status)
                raise KapitalbankError(None, f"HTTP {status}")
            try:
                payload = resp.json()
            except ValueError:
                raise KapitalbankError(None, "Invalid JSON in response") from None
            error = payload.get("error") if isinstance(payload, dict) else None
            if error:
                code = error.get("code")
                if code != 0:
                    logger.warning("kapitalbank %s %s error code %s", method, log_ctx, code)
                    raise KapitalbankError(code, _s(error.get("message")))
            return payload
        assert last is not None
        raise last

    def get_statement(self, *, account_no: str, branch: str, day: date) -> Statement:
        body = {"branch": branch, "account": account_no, "date": day.strftime("%d.%m.%Y")}
        payload = self._call("GetDoc1C", body, log_ctx=f"account={account_no}")
        result = payload.get("result") or {}
        docs = [
            StatementDoc(
                general_id=_s(d.get("general_id")),
                b2_id=_s(d.get("b2_id")),
                num=_s(d.get("num")),
                ddate=_parse_date(d.get("ddate")),
                vdate=_parse_date(d.get("vdate")),
                acc_dt=_s(d.get("acc_dt")),
                acc_ct=_s(d.get("acc_ct")),
                name_dt=_s(d.get("name_dt")),
                name_ct=_s(d.get("name_ct")),
                inn_dt=_s(d.get("inn_dt")),
                inn_ct=_s(d.get("inn_ct")),
                mfo_dt=_s(d.get("mfo_dt")),
                mfo_ct=_s(d.get("mfo_ct")),
                purpose=_s(d.get("purpose")),
                dtype=_s(d.get("dtype")),
                amount=_money(d.get("amount")),
                state=int(d.get("state") or 0),
                dir=int(d.get("dir") or 0),
            )
            for d in (result.get("content") or [])
        ]
        return Statement(
            docs=docs,
            saldo_in=_money(result.get("saldo_in")),
            saldo_out=None if result.get("saldo_out") is None else _money(result.get("saldo_out")),
            total_debit=_money(result.get("total_debit")),
            total_credit=_money(result.get("total_credit")),
            fin=bool(int(result.get("fin") or 0)),
            oper_day=_parse_date(result.get("oper_day")),
        )

    def list_accounts(self) -> list[BankListedAccount]:
        payload = self._call("APILogin", {}, log_ctx="list_accounts")
        result = payload.get("result") or {}
        accounts: list[BankListedAccount] = []
        for client in result.get("clients") or []:
            for a in client.get("accounts") or []:
                accounts.append(
                    BankListedAccount(
                        account_no=_s(a.get("account")),
                        branch=_code(a.get("branch"), 5),
                        name=_s(a.get("name")),
                        currency=_code(a.get("val"), 3),
                        state_name=_s(a.get("stateName")),
                        balance=_money(a.get("s_out")),
                    )
                )
        return accounts
