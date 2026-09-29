from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.modules.cash_withdrawals.fixtures import CashWithdrawalFixtures
from apps.modules.cash_withdrawals.models import CashWithdrawalReceipt, CashWithdrawalRule


class CashWithdrawalModelTests(CashWithdrawalFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_receipt_defaults_to_pending(self):
        receipt = self.make_receipt()
        self.assertEqual(receipt.status, CashWithdrawalReceipt.Status.PENDING)
        self.assertEqual(receipt.alert_count, 0)
        self.assertIsNone(receipt.cash_revenue_id)

    def test_one_receipt_per_request(self):
        req = self.make_request()
        self.make_receipt(req)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_receipt(req)

    def test_rule_unique_per_type_and_purpose(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashWithdrawalRule.objects.create(
                config=self.config,
                payment_type=self.rule.payment_type,
                payment_purpose=self.rule.payment_purpose,
                wallet=self.wallet,
            )
