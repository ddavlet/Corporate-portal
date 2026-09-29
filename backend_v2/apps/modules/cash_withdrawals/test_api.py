from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.cash_withdrawals.fixtures import PURPOSE, CashWithdrawalFixtures
from apps.modules.cash_withdrawals.models import CashWithdrawalConfig, CashWithdrawalRule
from apps.modules.requests.models import (
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.wallets.resolution import get_or_create_bank_wallet_for_account, get_or_create_cash_wallet
from apps.tenants.models import Tenant

URL = "/api/cash-withdrawals/config/"


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class ConfigApiTests(CashWithdrawalFixtures, APITestCase):
    def setUp(self):
        self.make_fixtures()
        form = RequestFormConfig.objects.create(tenant=self.tenant, updated_by=self.admin)
        pt = RequestFormPaymentTypeConfig.objects.create(config=form, payment_type="Перечисление", is_enabled=True)
        RequestPaymentPurposeConfig.objects.create(payment_type_config=pt, name=PURPOSE, is_active=True)
        self.client.force_authenticate(self.admin)

    def _payload(self, **overrides):
        data = {
            "is_active": True,
            "card_telegram_chat_id": self.group.id,
            "alert_telegram_chat_id": None,
            "alert_after_days": 2,
            "alert_repeat_every_days": 1,
            "alert_hour": 10,
            "confirmer_user_ids": [self.cashier.id],
            "alert_recipient_user_ids": [self.admin.id, self.accountant.id],
            "rules": [{"payment_type": "Перечисление", "payment_purpose": PURPOSE, "wallet_id": self.wallet.id}],
        }
        data.update(overrides)
        return data

    def test_get_returns_config_and_options(self):
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.data["is_active"])
        self.assertEqual(res.data["card_telegram_chat_id"], self.group.id)
        self.assertEqual(sorted(res.data["confirmer_user_ids"]), sorted([self.cashier.id, self.accountant.id]))
        self.assertEqual(res.data["rules"][0]["wallet_id"], self.wallet.id)
        opts = res.data["options"]
        self.assertIn({"id": self.wallet.id, "label": "Основная касса", "currency": "UZS"}, opts["wallets"])
        self.assertIn({"payment_type": "Перечисление", "purposes": [PURPOSE]}, opts["payment_purposes"])
        self.assertIn({"id": self.group.id, "name": "Касса Aqua"}, opts["telegram_chats"])
        cashier_opt = next(u for u in opts["users"] if u["id"] == self.cashier.id)
        self.assertTrue(cashier_opt["has_telegram"])

    def test_get_without_config_returns_defaults(self):
        CashWithdrawalConfig.objects.all().delete()
        res = self.client.get(URL, HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["is_active"])
        self.assertEqual(res.data["alert_after_days"], 3)
        self.assertEqual(res.data["rules"], [])

    def test_put_replaces_config(self):
        res = self.client.put(URL, self._payload(), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200, res.content)
        self.config.refresh_from_db()
        self.assertEqual(self.config.alert_after_days, 2)
        self.assertEqual(self.config.alert_hour, 10)
        self.assertEqual(list(self.config.confirmers.values_list("user_id", flat=True)), [self.cashier.id])
        self.assertEqual(
            sorted(self.config.alert_recipients.values_list("user_id", flat=True)),
            sorted([self.admin.id, self.accountant.id]),
        )
        self.assertEqual(self.config.updated_by_id, self.admin.id)

    def test_put_rejects_foreign_wallet(self):
        other = Tenant.objects.create(name="Other", subdomain="other", is_active=True)
        foreign = get_or_create_cash_wallet(tenant=other, currency="UZS")
        rules = [{"payment_type": "Перечисление", "payment_purpose": PURPOSE, "wallet_id": foreign.id}]
        res = self.client.put(URL, self._payload(rules=rules), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(CashWithdrawalRule.objects.get().wallet_id, self.wallet.id)

    def test_put_rejects_bank_wallet(self):
        bank = get_or_create_bank_wallet_for_account(tenant=self.tenant, account_no="20208000123456789012", mfo="00450")
        rules = [{"payment_type": "Перечисление", "payment_purpose": PURPOSE, "wallet_id": bank.id}]
        res = self.client.put(URL, self._payload(rules=rules), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

    def test_put_rejects_duplicate_rules(self):
        rule = {"payment_type": "Перечисление", "payment_purpose": PURPOSE, "wallet_id": self.wallet.id}
        res = self.client.put(URL, self._payload(rules=[rule, dict(rule)]), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)

    def test_put_active_requires_rules_and_confirmers(self):
        res = self.client.put(URL, self._payload(rules=[]), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        res = self.client.put(URL, self._payload(confirmer_user_ids=[]), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 400)
        res = self.client.put(URL, self._payload(is_active=False, rules=[], confirmer_user_ids=[]), format="json", HTTP_HOST=self.host)
        self.assertEqual(res.status_code, 200)

    def test_put_rejects_non_member_user_and_bad_numbers(self):
        from django.contrib.auth import get_user_model

        stranger = get_user_model().objects.create_user(username="stranger", password="x")
        self.assertEqual(
            self.client.put(URL, self._payload(confirmer_user_ids=[stranger.id]), format="json", HTTP_HOST=self.host).status_code,
            400,
        )
        self.assertEqual(
            self.client.put(URL, self._payload(alert_hour=24), format="json", HTTP_HOST=self.host).status_code, 400
        )
        self.assertEqual(
            self.client.put(URL, self._payload(alert_repeat_every_days=0), format="json", HTTP_HOST=self.host).status_code,
            400,
        )

    def test_non_admin_forbidden(self):
        self.client.force_authenticate(self.cashier)
        self.assertEqual(self.client.get(URL, HTTP_HOST=self.host).status_code, 403)
