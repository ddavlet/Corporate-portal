import importlib

from django.apps import apps as django_apps
from django.test import TestCase

from apps.modules.cash_desk.models import CashDeskConfig
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.tenants.models import Tenant

seed = importlib.import_module("apps.modules.cash_desk.migrations.0002_seed_cash_groups").seed


class SeedCashGroupsTests(TestCase):
    def test_creates_missing_group_and_inactive_config(self):
        tenant = Tenant.objects.create(name="New", subdomain="lemonnew")
        seed(django_apps, None)
        chat = TenantTelegramChat.objects.get(tenant=tenant, chat_id="-5457282029")
        self.assertEqual(chat.name, "Касса NEW")
        config = CashDeskConfig.objects.get(tenant=tenant)
        self.assertFalse(config.is_active)
        self.assertEqual(config.telegram_chat_id, chat.id)

    def test_reuses_existing_group_without_renaming(self):
        tenant = Tenant.objects.create(name="Qulay", subdomain="qulay")
        chat = TenantTelegramChat.objects.create(tenant=tenant, name="X", chat_id="-4841328641")
        seed(django_apps, None)
        chat.refresh_from_db()
        self.assertEqual(chat.name, "X")
        self.assertEqual(TenantTelegramChat.objects.filter(tenant=tenant).count(), 1)
        self.assertEqual(CashDeskConfig.objects.get(tenant=tenant).telegram_chat_id, chat.id)

    def test_keeps_existing_config(self):
        tenant = Tenant.objects.create(name="Aqua", subdomain="lemonaqua")
        other = TenantTelegramChat.objects.create(tenant=tenant, name="Other", chat_id="-100777")
        CashDeskConfig.objects.create(tenant=tenant, is_active=True, telegram_chat=other)
        seed(django_apps, None)
        config = CashDeskConfig.objects.get(tenant=tenant)
        self.assertTrue(config.is_active)
        self.assertEqual(config.telegram_chat_id, other.id)

    def test_missing_tenant_is_skipped(self):
        seed(django_apps, None)
        self.assertEqual(CashDeskConfig.objects.count(), 0)
