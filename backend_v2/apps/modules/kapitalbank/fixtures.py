"""Shared test fixtures for kapitalbank tests (not a test module itself)."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from apps.modules.wallets.models import CorporateCardAccount
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account, get_or_create_corporate_wallet
from apps.tenants.models import Tenant, TenantModuleConfig

User = get_user_model()

MFO = "01158"
ACCOUNT_1 = "20208000504843803001"
ACCOUNT_2 = "20208000904843803004"
CARD_REF = "8600490000000001"


class KapitalbankFixtures:
    """Mixin for TestCase: call self.make_fixtures() in setUp."""

    def make_fixtures(self) -> None:
        User.objects.update_or_create(pk=1, defaults={"username": "system"})
        self.tenant = Tenant.objects.create(name="Kolberg Plus", subdomain="kp", is_active=True)
        self.owner = User.objects.create_user(
            username="kb-owner", password="x", full_name="Владелец", telegram_chat_id=1387986, telegram_from_id=1387986
        )
        self.wallet1 = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=ACCOUNT_1, mfo=MFO)
        self.wallet2 = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no=ACCOUNT_2, mfo=MFO)
        self.bank_account1 = self.wallet1.bank_account
        self.bank_account2 = self.wallet2.bank_account
        self.card_wallet = get_or_create_corporate_wallet(tenant=self.tenant, currency="UZS")
        self.card_account = self.card_wallet.corporate_card_account
        CorporateCardAccount.objects.filter(pk=self.card_account.pk).update(external_ref=CARD_REF)
        self.card_account.refresh_from_db()
        TenantModuleConfig.objects.create(tenant=self.tenant, module_key="bank", is_enabled=True)


def _doc(n: int, *, amount: int, dir_: int, dt: tuple[str, str, str], ct: tuple[str, str, str]) -> dict:
    return {
        "time": "09:15:30",
        "input_date": "24.02.2026",
        "input_time": "10:30:00",
        "client_id": 100001,
        "num": f"{n:012d}",
        "branch": MFO,
        "general_id": f"GEN00{n}",
        "b2_id": f"B2_00{n}",
        "uniq": f"UNIQ00{n}",
        "ddate": "24.02.2026",
        "vdate": "24.02.2026",
        "stime": "09:15:00",
        "mfo_dt": dt[0],
        "acc_dt": dt[1],
        "name_dt": dt[2],
        "inn_dt": "201122919",
        "mfo_ct": ct[0],
        "acc_ct": ct[1],
        "name_ct": ct[2],
        "inn_ct": "201122920",
        "purpose": f"Оплата по счету {n}",
        "purp_code": None,
        "amount": amount,
        "dtype": "21",
        "state": 1,
        "dir": dir_,
        "err": "0",
        "err_msg": "",
        "anor": 0,
    }


# Anonymized GetDoc1C response (KapitalAPI_V3.pdf, section 4.1); money in tiyin.
STATEMENT_JSON = {
    "error": None,
    "id": 1234567890123456,
    "result": {
        "content": [
            _doc(1, amount=5000000, dir_=1, dt=("00365", "20208840100400002020", "ООО Плательщик"), ct=(MFO, ACCOUNT_1, "ООО Получатель")),
            _doc(2, amount=1000000, dir_=2, dt=(MFO, ACCOUNT_1, "ООО Получатель"), ct=("00365", "20208840100400002020", "ООО Плательщик")),
        ],
        "total_debit": 1000000,
        "total_credit": 5000000,
        "saldo_in": 42000000,
        "saldo_out": 46000000,
        "fin": 1,
        "oper_day": "24.02.2026",
    },
}


def _account(n: int, account: str, s_out: int) -> dict:
    return {
        "aid": n,
        "branch": MFO,
        "account": account,
        "name": f"Расчетный счет {n}",
        "val": "000",
        "o_date": "01.01.2020",
        "l_date": "24.02.2026",
        "s_in": 0,
        "s_out": s_out,
        "dt": 0,
        "ct": 0,
        "canpay": 1,
        "state": 1,
        "notif_in": 0,
        "notif_out": 0,
        "stateName": "Открыт",
        "special": [],
    }


def _client(n: int, account: str, s_out: int) -> dict:
    return {
        "id": n,
        "branch": MFO,
        "code": f"CL{n}",
        "name": f"ООО Организация {n}",
        "oper_day": "24.02.2026",
        "inn": "201122919",
        "phone": "+998000000000",
        "accounts": [_account(n, account, s_out)],
    }


# Anonymized APILogin response (KapitalAPI_V3.pdf, section 1.1): two organizations, one account each.
APILOGIN_JSON = {
    "error": None,
    "id": 107893348,
    "result": {
        "login": "IB#user",
        "sid": "example-session-id",
        "clients": [_client(1, ACCOUNT_1, 46000000), _client(2, ACCOUNT_2, 12345)],
    },
}


# ── Payroll transit account (23106): card payouts of salaries. All names and numbers are made up. ──

TRANSIT_ACCOUNT = "23106000900000000001"
TRANSIT_DAY = "02.10.2026"
PAYROLL_CLIENT_ID = 100001
CARD_ACCOUNTS = (
    "22618000900000000001",
    "22618000900000000002",
    "22618000900000000003",
    "22618000900000000004",  # only in GetZP1C (ZP_JSON)
    "22618000900000000099",  # in neither directory
)
CARD_NAMES = ("TESTOV ALISHER", "NAMUNA DILNOZA", "MISOLOV BOBUR", "SINOVA MALIKA", "NOMALUM JASUR")
CARD_AMOUNTS_TIYIN = (500000000, 400000000, 350000000, 280800000, 150000000)  # 16 808 000.00 sum in total
BATCH_NUM = "777"
# Fake passport / INN / birth date sent by GetWorkers1C: must never reach the DB, payloads or logs.
PII_MARKERS = ("ZZ9876543", "998877665", "31.12.1985")


def _transit_doc(n: int, *, dtype: str, amount: int, incoming: bool, card: str = "", name: str = "") -> dict:
    payer = (MFO, ACCOUNT_1, "ООО Организация 1")
    transit = (MFO, TRANSIT_ACCOUNT, "Транзитный счёт ЗП")
    card_side = (MFO, card, "UZCARD PROCESSING")
    dt, ct = (payer, transit) if incoming else (transit, card_side)
    purpose = (
        "Перечисление заработной платы по ведомости №8"
        if incoming
        else f"Заработная плата за июль от {TRANSIT_DAY} сотруднику {name}"
    )
    return {
        "num": BATCH_NUM if incoming else f"{n:06d}",
        "branch": MFO,
        "general_id": f"TRGEN{n}",
        "b2_id": f"TRB2{n}",
        "uniq": None,
        "ddate": TRANSIT_DAY,
        "vdate": TRANSIT_DAY,
        "mfo_dt": dt[0],
        "acc_dt": dt[1],
        "name_dt": dt[2],
        "inn_dt": "",
        "mfo_ct": ct[0],
        "acc_ct": ct[1],
        "name_ct": ct[2],
        "inn_ct": "",
        "purpose": purpose,
        "amount": amount,
        "dtype": dtype,
        "state": 3,
        "dir": 1 if incoming else 2,
    }


# GetDoc1C on the transit account: five dtype 06 card credits and the incoming dtype 21 they add up
# to. The dtype 21 is last on purpose: the bank does not order ``content``.
TRANSIT_STATEMENT_JSON = {
    "error": None,
    "result": {
        "content": [
            *[
                _transit_doc(n + 1, dtype="06", amount=CARD_AMOUNTS_TIYIN[n], incoming=False, card=CARD_ACCOUNTS[n], name=CARD_NAMES[n])
                for n in range(5)
            ],
            _transit_doc(100, dtype="21", amount=sum(CARD_AMOUNTS_TIYIN), incoming=True),
        ],
        "total_debit": sum(CARD_AMOUNTS_TIYIN),
        "total_credit": sum(CARD_AMOUNTS_TIYIN),
        "saldo_in": 0,
        "saldo_out": 0,
        "fin": 1,
        "oper_day": TRANSIT_DAY,
    },
}


def _worker(n: int, *, masked_card: str) -> dict:
    return {
        "acc": CARD_ACCOUNTS[n],
        "employee_id": f"E100{n + 1}",
        "fio": CARD_NAMES[n],
        "masked_card": masked_card,
        "branch": 1158,
        "customer_id": f"C{n + 1}",
        "birthday": PII_MARKERS[2],
        "birth_date": PII_MARKERS[2],
        "inn": PII_MARKERS[1],
        "passport": PII_MARKERS[0],
    }


# GetWorkers1C: the first three card accounts; the third one sends a full card number.
WORKERS_JSON = {
    "error": None,
    "result": [
        _worker(0, masked_card="8600********0001"),
        _worker(1, masked_card="9860********0002"),
        _worker(2, masked_card="5614000011110003"),
    ],
}

# GetZP1C: one sheet for the day, partial (the bank returns only part of the rows).
ZP_JSON = {
    "error": None,
    "result": [
        {
            "name": "Ведомость №8 (02.10.2026)",
            "general_pay": 1,
            "date_oper": TRANSIT_DAY,
            "state": 3,
            "type": 1,
            "file_name": None,
            "branch": None,
            "customer_id": "C0",
            "sign": 1,
            "documents": [
                {
                    "acc": CARD_ACCOUNTS[3],
                    "amount": CARD_AMOUNTS_TIYIN[3],
                    "employee_id": "E1004",
                    "fio": CARD_NAMES[3],
                    "general_id": "",
                    "iid": "",
                },
                {
                    "acc": CARD_ACCOUNTS[0],
                    "amount": CARD_AMOUNTS_TIYIN[0],
                    "employee_id": "E1001",
                    "fio": CARD_NAMES[0],
                    "general_id": "",
                    "iid": "",
                },
            ],
        }
    ],
}

# APILogin with the payroll transit account in zp_accs (branch and id come as numbers).
APILOGIN_WITH_ZP_JSON = {
    "error": None,
    "result": {
        "login": "IB#user",
        "sid": "example-session-id",
        "clients": [
            {
                **_client(1, ACCOUNT_1, 46000000),
                "id": PAYROLL_CLIENT_ID,
                "branch": 1158,
                "zp_accs": [{"branch": 1158, "account": TRANSIT_ACCOUNT}],
                "zp_humo_accs": [],
                "zp_upi_accs": [],
            }
        ],
    },
}
