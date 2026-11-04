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
