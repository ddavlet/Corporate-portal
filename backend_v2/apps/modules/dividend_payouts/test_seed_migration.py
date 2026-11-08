import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from apps.modules.dividend_payouts.fixtures import FOUNDER_PURPOSE, PARTNER_PURPOSE, DividendPayoutFixtures
from apps.modules.dividend_payouts.models import DividendPayoutRule
from apps.modules.investments.models import InvestReturn
from apps.modules.requests.models import Request, RequestPaymentPurposeConfig
from apps.tenants.models import Tenant

seed = importlib.import_module("apps.modules.dividend_payouts.migrations.0002_seed_rules").seed

PRINCIPAL = InvestReturn.ReturnType.PRINCIPAL
DIVIDEND = InvestReturn.ReturnType.DIVIDEND
INVESTOR = InvestReturn.Recipient.INVESTOR
PARTNER = InvestReturn.Recipient.PARTNER


def rules_of(tenant) -> set[tuple[str, str, str, bool]]:
    return set(
        DividendPayoutRule.objects.filter(tenant=tenant).values_list(
            "payment_purpose", "return_type", "recipient", "is_active"
        )
    )


class SeedRulesTests(DividendPayoutFixtures, TestCase):
    def test_seeds_rules_per_tenant(self):
        lemon = Tenant.objects.create(name="HAVO", subdomain="lemonhavo")
        neuron = Tenant.objects.create(name="Neuron", subdomain="neuron")
        qulay = Tenant.objects.create(name="Qulay", subdomain="qulay")
        kp = Tenant.objects.create(name="KP", subdomain="kp")
        unrelated = Tenant.objects.create(name="Other", subdomain="other")

        seed(django_apps, None)

        self.assertEqual(
            rules_of(lemon),
            {(FOUNDER_PURPOSE, PRINCIPAL, INVESTOR, True), (PARTNER_PURPOSE, PRINCIPAL, PARTNER, True)},
        )
        self.assertEqual(rules_of(neuron), {("Дивиденды", PRINCIPAL, INVESTOR, True)})
        self.assertEqual(
            rules_of(qulay),
            {(FOUNDER_PURPOSE, DIVIDEND, INVESTOR, True), (PARTNER_PURPOSE, DIVIDEND, PARTNER, True)},
        )
        self.assertEqual(rules_of(kp), {("Дивиденды", DIVIDEND, INVESTOR, True)})
        self.assertEqual(rules_of(unrelated), set())

    def test_missing_tenants_are_skipped(self):
        seed(django_apps, None)
        self.assertFalse(DividendPayoutRule.objects.exists())

    def test_idempotent_and_keeps_existing_rule(self):
        tenant = Tenant.objects.create(name="Aqua", subdomain="lemonaqua")
        DividendPayoutRule.objects.create(
            tenant=tenant, payment_purpose="дивиденды УЧРЕДИТЕЛЮ", return_type=DIVIDEND, recipient=PARTNER,
            is_active=False,
        )
        seed(django_apps, None)
        seed(django_apps, None)
        self.assertEqual(
            rules_of(tenant),
            {("дивиденды УЧРЕДИТЕЛЮ", DIVIDEND, PARTNER, False), (PARTNER_PURPOSE, PRINCIPAL, PARTNER, True)},
        )


class SplitQulayPurposeTests(DividendPayoutFixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.qulay = Tenant.objects.create(name="Qulay", subdomain="qulay", is_active=True)

    def _purposes(self, payment_type: str) -> dict[str, tuple[str, bool]]:
        rows = RequestPaymentPurposeConfig.objects.filter(
            payment_type_config__config__tenant=self.qulay, payment_type_config__payment_type=payment_type
        )
        return {row.name: (row.category, row.is_active) for row in rows}

    def test_splits_active_dividend_purpose_per_payment_type(self):
        self.make_purpose(tenant=self.qulay, name="Дивиденды", category="Учредители")
        self.make_purpose(tenant=self.qulay, name="Аренда", category="Офис")
        self.make_purpose(tenant=self.qulay, name="Дивиденды", category="Наличные выплаты", payment_type="Наличные")
        self.make_purpose(
            tenant=self.qulay, name="Дивиденды", category="Карта", payment_type="Платежная карта", is_active=False
        )

        seed(django_apps, None)

        self.assertEqual(
            self._purposes(Request.PAYMENT_TYPE_TRANSFER),
            {
                "Дивиденды": ("Учредители", False),
                FOUNDER_PURPOSE: ("Учредители", True),
                PARTNER_PURPOSE: ("Учредители", True),
                "Аренда": ("Офис", True),
            },
        )
        self.assertEqual(
            self._purposes(Request.PAYMENT_TYPE_CASH),
            {
                "Дивиденды": ("Наличные выплаты", False),
                FOUNDER_PURPOSE: ("Наличные выплаты", True),
                PARTNER_PURPOSE: ("Наличные выплаты", True),
            },
        )
        # Inactive «Дивиденды» is left alone: no new purposes there.
        self.assertEqual(self._purposes(Request.PAYMENT_TYPE_CARD), {"Дивиденды": ("Карта", False)})

    def test_reuses_existing_new_purpose_and_reactivates_it(self):
        self.make_purpose(tenant=self.qulay, name="Дивиденды", category="Учредители")
        self.make_purpose(tenant=self.qulay, name=FOUNDER_PURPOSE, category="Своя", is_active=False)

        seed(django_apps, None)
        seed(django_apps, None)

        self.assertEqual(
            self._purposes(Request.PAYMENT_TYPE_TRANSFER),
            {
                "Дивиденды": ("Учредители", False),
                FOUNDER_PURPOSE: ("Своя", True),
                PARTNER_PURPOSE: ("Учредители", True),
            },
        )

    def test_other_tenants_purposes_untouched(self):
        self.make_purpose(name="Дивиденды")  # lemonaqua from fixtures
        seed(django_apps, None)
        purposes = RequestPaymentPurposeConfig.objects.filter(payment_type_config__config__tenant=self.tenant)
        self.assertEqual(list(purposes.values_list("name", "is_active")), [("Дивиденды", True)])
