from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from rest_framework.response import Response

from apps.modules.bank_expenses.models import BankExpense, BankRevenue
from apps.modules.corporate_card.models import CardRevenue
from apps.modules.n8n_integration.views import N8nBankExpenseBatchUpsertView
from django.contrib.auth import get_user_model
from apps.modules.vendors.models import Vendor
from apps.tenants.models import Tenant

from .client import Statement, StatementDoc
from .fixtures import ACCOUNT_1, CARD_REF, MFO, KapitalbankFixtures
from .ingest import IngestError, ingest_statement
from .models import BankAccountLink

COUNTERPARTY = "20208840100400002020"


def make_doc(n, *, incoming, account=ACCOUNT_1, counterparty=COUNTERPARTY, inn="201122919", purpose=None, amount="50000.00"):
    ours = (MFO, account, "ООО Наша")
    theirs = ("00365", counterparty, "ООО Контрагент")
    dt, ct = (theirs, ours) if incoming else (ours, theirs)
    return StatementDoc(
        general_id=f"GEN00{n}",
        b2_id=f"B2_00{n}",
        num=f"{n:012d}",
        ddate=date(2026, 2, 24),
        vdate=date(2026, 2, 24),
        acc_dt=dt[1],
        acc_ct=ct[1],
        name_dt=dt[2],
        name_ct=ct[2],
        inn_dt=inn if incoming else "201122919",
        inn_ct="201122919" if incoming else inn,
        mfo_dt=dt[0],
        mfo_ct=ct[0],
        purpose=purpose or f"Оплата по счету {n}",
        dtype="21",
        amount=Decimal(amount),
        state=1,
        dir=1 if incoming else 2,
    )


def make_statement(*docs):
    return Statement(
        docs=list(docs),
        saldo_in=Decimal(0),
        saldo_out=Decimal(0),
        total_debit=Decimal(0),
        total_credit=Decimal(0),
        fin=True,
        oper_day=date(2026, 2, 24),
    )


class IngestStatementTests(KapitalbankFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.link = BankAccountLink.objects.create(
            tenant=self.tenant,
            account_no=ACCOUNT_1,
            branch=MFO,
            decision=BankAccountLink.LINKED,
            bank_account=self.bank_account1,
        )
        self.statement = make_statement(make_doc(1, incoming=True), make_doc(2, incoming=False))

    def test_creates_revenue_expense_and_vendor_like_n8n(self):
        result = ingest_statement(self.link, self.statement)

        self.assertEqual(result.created, 2)
        self.assertEqual(result.missing_external_ids, [])
        self.assertEqual(BankRevenue.objects.get(external_id="GEN001").wallet, self.wallet1)
        self.assertEqual(BankExpense.objects.get(external_id="GEN002").wallet, self.wallet1)
        self.assertTrue(Vendor.objects.filter(tenant=self.tenant, account_number=COUNTERPARTY).exists())

    def test_second_run_creates_nothing_and_keeps_admin_edits(self):
        ingest_statement(self.link, self.statement)
        BankExpense.objects.filter(external_id="GEN002").update(payment_purpose="Исправлено админом")

        result = ingest_statement(self.link, self.statement)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped_existing, 2)
        self.assertEqual(BankExpense.objects.get(external_id="GEN002").payment_purpose, "Исправлено админом")

    def test_doc_moved_to_other_tenant_is_not_recreated(self):
        ingest_statement(self.link, self.statement)
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        BankRevenue.objects.filter(external_id="GEN001").update(tenant=other)

        result = ingest_statement(self.link, self.statement)

        self.assertEqual(result.created, 0)
        self.assertEqual(result.missing_external_ids, [])
        self.assertEqual(BankRevenue.objects.filter(external_id="GEN001").count(), 1)

    def test_empty_statement_posts_nothing(self):
        with patch("apps.modules.n8n_integration.views._N8nBatchBaseView.post") as post:
            result = ingest_statement(self.link, make_statement())
        post.assert_not_called()
        self.assertEqual(result.created, 0)

    def test_rejected_batch_raises_and_rolls_back(self):
        with patch.object(N8nBankExpenseBatchUpsertView, "post", return_value=Response({"detail": "bad"}, status=400)):
            with self.assertRaises(IngestError) as ctx:
                ingest_statement(self.link, self.statement)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(BankExpense.objects.count(), 0)
        self.assertEqual(BankRevenue.objects.count(), 0)
        self.assertEqual(Vendor.objects.filter(tenant=self.tenant).count(), 0)

    def test_expense_to_counterparty_without_inn_creates_expense_but_no_vendor(self):
        statement = make_statement(make_doc(3, incoming=False, inn=""))

        result = ingest_statement(self.link, statement)

        self.assertEqual(result.created, 1)
        self.assertTrue(BankExpense.objects.filter(external_id="GEN003", wallet=self.wallet1).exists())
        self.assertFalse(Vendor.objects.filter(tenant=self.tenant).exists())

    def test_dry_run_writes_nothing_and_reports_diffs(self):
        first = make_statement(make_doc(2, incoming=False))
        ingest_statement(self.link, first)
        BankExpense.objects.filter(external_id="GEN002").update(payment_purpose="Другое назначение")

        result = ingest_statement(self.link, self.statement, dry_run=True)

        self.assertEqual(
            result.field_diffs,
            [
                {
                    "external_id": "GEN002",
                    "field": "payment_purpose",
                    "portal": "Другое назначение",
                    "bank": "Оплата по счету 2",
                }
            ],
        )
        self.assertEqual(result.created, 0)
        self.assertEqual([i["external_id"] for i in result.would_create], ["GEN001"])
        self.assertEqual(BankRevenue.objects.count(), 0)
        self.assertEqual(BankExpense.objects.count(), 1)

    def test_card_statement_goes_to_linked_card_wallet(self):
        link = BankAccountLink.objects.create(
            tenant=self.tenant,
            account_no=CARD_REF,
            branch=MFO,
            decision=BankAccountLink.LINKED,
            card_account=self.card_account,
        )
        statement = make_statement(make_doc(5, incoming=True, account=CARD_REF))

        result = ingest_statement(link, statement)

        self.assertEqual(result.created, 1)
        self.assertEqual(CardRevenue.objects.get(external_id="GEN005").wallet, link.wallet())

    def test_legacy_duplicate_skipped_by_view_is_not_counted_and_is_missing(self):
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by=get_user_model().objects.get(pk=1),
            external_id="",
            row_no=1,
            doc_date=date(2026, 2, 24),
            process_date=date(2026, 2, 24),
            expense_year=2026,
            expense_month=2,
            expense_day=24,
            doc_no="000000000002",
            debit_turnover=Decimal("50000.00"),
            payment_purpose="Оплата по счету 2",
            wallet=self.wallet1,
        )

        result = ingest_statement(self.link, make_statement(make_doc(2, incoming=False)))

        self.assertEqual(result.created, 0)
        self.assertEqual(result.missing_external_ids, ["GEN002"])

    def test_doc_on_other_wallet_of_same_tenant_is_not_sent(self):
        BankExpense.objects.create(
            tenant=self.tenant,
            created_by=get_user_model().objects.get(pk=1),
            external_id="GEN002",
            row_no=1,
            doc_date=date(2026, 2, 24),
            process_date=date(2026, 2, 24),
            expense_year=2026,
            expense_month=2,
            expense_day=24,
            doc_no="X",
            debit_turnover=Decimal("1.00"),
            payment_purpose="other",
            wallet=self.wallet2,
        )

        result = ingest_statement(self.link, self.statement)

        self.assertEqual(result.created, 1)
        self.assertEqual(result.missing_external_ids, ["GEN002"])
        self.assertEqual(BankExpense.objects.get(external_id="GEN002").wallet, self.wallet2)

    def test_bank_account_mismatch_raises_409(self):
        self.link.bank_account = self.bank_account2
        with self.assertRaises(IngestError) as ctx:
            ingest_statement(self.link, self.statement)
        self.assertEqual(ctx.exception.status, 409)
