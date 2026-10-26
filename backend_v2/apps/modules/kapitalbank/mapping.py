"""Pure mapping of Kapitalbank statement documents to n8n batch upsert items.

Field names and values replicate the live n8n workflow (Edit Fields2/3/4/5),
including the typo in the card top-up operation name.
"""

from __future__ import annotations

from decimal import Decimal

from .client import StatementDoc

CARD_TOPUP_OPERATION = "Пополение корп-карты"
_TZ = "+05:00"


def is_incoming(doc: StatementDoc, our_account: str) -> bool:
    return doc.acc_ct == our_account


def _money(value: Decimal) -> str:
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def _inn(value: str):
    # n8n: `inn || 0`
    return value or 0


def _bank_base(doc: StatementDoc, *, name: str, inn: str, account_no: str, mfo: str) -> dict:
    return {
        "doc_date": doc.ddate.isoformat(),
        "process_date": doc.vdate.isoformat(),
        "account_name": name,
        "inn": _inn(inn),
        "account_no": account_no,
        "mfo": mfo,
        "payment_purpose": doc.purpose,
        "doc_no": doc.num,
        "external_id": str(doc.general_id),
    }


def bank_revenue_item(doc: StatementDoc) -> dict:
    item = _bank_base(doc, name=doc.name_dt, inn=doc.inn_dt, account_no=doc.acc_dt, mfo=doc.mfo_dt)
    item["kredit_turnover"] = _money(doc.amount)
    return item


def bank_expense_item(doc: StatementDoc) -> dict:
    item = _bank_base(doc, name=doc.name_ct, inn=doc.inn_ct, account_no=doc.acc_ct, mfo=doc.mfo_ct)
    item["debit_turnover"] = _money(doc.amount)
    return item


def vendor_items(expense_items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result: list[dict] = []
    for item in expense_items:
        account_no = item["account_no"]
        if account_no in seen:
            continue
        seen.add(account_no)
        result.append(
            {
                "kind": "transfer",
                "name": item["account_name"],
                "inn": _inn(item["inn"]) if item["inn"] != 0 else 0,
                "account_no": account_no,
            }
        )
    return result


def card_revenue_item(doc: StatementDoc, *, wallet_id: int) -> dict:
    return {
        "revenue_at": f"{doc.ddate.isoformat()}T00:00:00{_TZ}",
        "total_sum": _money(doc.amount),
        "currency": "UZS",
        "counterparty": doc.name_dt,
        "operation": CARD_TOPUP_OPERATION,
        "comment": doc.purpose,
        "external_id": str(doc.general_id),
        "account": doc.acc_dt,
        "wallet_id": wallet_id,
        "payload": {
            "doc_no": doc.num,
            "inn": _inn(doc.inn_dt),
            "mfo": doc.mfo_dt,
            "process_date": doc.vdate.isoformat(),
            "account_no": doc.acc_dt,
            "account_name": doc.name_dt,
        },
    }


def card_expense_item(doc: StatementDoc, *, wallet_id: int) -> dict:
    return {
        "expense_at": f"{doc.ddate.isoformat()}T00:00:00{_TZ}",
        "amount": _money(doc.amount),
        "currency": "UZS",
        "title": doc.name_dt,
        "note": doc.purpose,
        "external_id": str(doc.general_id),
        "wallet_id": wallet_id,
        "payload": {
            "doc_no": doc.num,
            "inn": _inn(doc.inn_ct),
            "mfo": doc.mfo_ct,
            "process_date": doc.vdate.isoformat(),
            "account_no": doc.acc_ct,
            "account_name": doc.name_ct,
        },
    }
