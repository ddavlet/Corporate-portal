"""
Tests for the "contains_all_words" operator of request_not_required_rules.

Covers:
  1. is_request_required_for_expense() matches regardless of word order and case
  2. is_request_required_for_expense() does not match when a word is missing
  3. the "eq" operator keeps requiring an exact match (unaffected by the new operator)
  4. the config serializer accepts the new operator and rejects unknown ones
"""

from types import SimpleNamespace

from django.test import TestCase

from apps.modules.requests.models import Request, RequestApprovalConfig, RequestApprovalPaymentTypeConfig
from apps.modules.requests.request_required import is_request_required_for_expense
from apps.modules.requests.serializers import RequestApprovalConfigPayloadSerializer
from apps.tenants.models import Tenant


class ContainsAllWordsRuleTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme", is_active=True)
        appr_cfg = RequestApprovalConfig.objects.create(tenant=self.tenant)
        self.pt_cfg = RequestApprovalPaymentTypeConfig.objects.create(
            config=appr_cfg,
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            is_enabled=True,
        )

    def _set_rule(self, *, field="payment_purpose", operator, value):
        self.pt_cfg.request_not_required_rules = [{"field": field, "operator": operator, "value": value}]
        self.pt_cfg.save(update_fields=["request_not_required_rules"])

    def test_matches_regardless_of_word_order_and_case(self):
        self._set_rule(operator="contains_all_words", value="тариф, CORPORATE")
        expense = SimpleNamespace(payment_purpose="qfeqwfwe corPOrate ТАРИФ")
        required = is_request_required_for_expense(
            tenant=self.tenant, payment_type=Request.PAYMENT_TYPE_TRANSFER, expense_obj=expense
        )
        self.assertFalse(required)

    def test_does_not_match_when_a_word_is_missing(self):
        self._set_rule(operator="contains_all_words", value="тариф, CORPORATE")
        expense = SimpleNamespace(payment_purpose="corporate only")
        required = is_request_required_for_expense(
            tenant=self.tenant, payment_type=Request.PAYMENT_TYPE_TRANSFER, expense_obj=expense
        )
        self.assertTrue(required)

    def test_eq_operator_still_requires_exact_match(self):
        self._set_rule(operator="eq", value="тариф CORPORATE")
        expense = SimpleNamespace(payment_purpose="qfeqwfwe corPOrate ТАРИФ")
        required = is_request_required_for_expense(
            tenant=self.tenant, payment_type=Request.PAYMENT_TYPE_TRANSFER, expense_obj=expense
        )
        self.assertTrue(required)

    def test_serializer_accepts_contains_all_words_operator(self):
        payload = {
            "payment_types": [
                {
                    "payment_type": Request.PAYMENT_TYPE_TRANSFER,
                    "request_not_required_rules": [
                        {"field": "payment_purpose", "operator": "contains_all_words", "value": "тариф, CORPORATE"}
                    ],
                }
            ]
        }
        serializer = RequestApprovalConfigPayloadSerializer(
            data=payload, context={"request": SimpleNamespace(tenant=self.tenant)}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_serializer_rejects_unknown_operator(self):
        payload = {
            "payment_types": [
                {
                    "payment_type": Request.PAYMENT_TYPE_TRANSFER,
                    "request_not_required_rules": [
                        {"field": "payment_purpose", "operator": "regex", "value": "тариф"}
                    ],
                }
            ]
        }
        serializer = RequestApprovalConfigPayloadSerializer(
            data=payload, context={"request": SimpleNamespace(tenant=self.tenant)}
        )
        self.assertFalse(serializer.is_valid())
