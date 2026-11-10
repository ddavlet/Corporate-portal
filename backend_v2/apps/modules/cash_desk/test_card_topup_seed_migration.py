import importlib

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.cash_desk.models import CardTopupNotifyConfig
from apps.tenants.models import Tenant, TenantMembership

seed = importlib.import_module("apps.modules.cash_desk.migrations.0005_seed_card_topup_neuron").seed
User = get_user_model()


class SeedCardTopupNeuronTests(TestCase):
    def setUp(self):
        self.neuron = Tenant.objects.create(name="Neuron", subdomain="neuron", is_active=True)
        self.user18, _ = User.objects.update_or_create(pk=18, defaults={"username": "ct-u18", "full_name": "Илхом"})

    def test_creates_active_config_for_member(self):
        TenantMembership.objects.create(tenant=self.neuron, user=self.user18, is_active=True)
        seed(django_apps, None)
        config = CardTopupNotifyConfig.objects.get(tenant=self.neuron)
        self.assertTrue(config.is_active)
        self.assertEqual(list(config.recipients.values_list("id", flat=True)), [18])

    def test_idempotent(self):
        TenantMembership.objects.create(tenant=self.neuron, user=self.user18, is_active=True)
        seed(django_apps, None)
        seed(django_apps, None)
        self.assertEqual(CardTopupNotifyConfig.objects.filter(tenant=self.neuron).count(), 1)
        self.assertEqual(CardTopupNotifyConfig.objects.get(tenant=self.neuron).recipients.count(), 1)

    def test_keeps_existing_config(self):
        TenantMembership.objects.create(tenant=self.neuron, user=self.user18, is_active=True)
        CardTopupNotifyConfig.objects.create(tenant=self.neuron, is_active=False)
        seed(django_apps, None)
        config = CardTopupNotifyConfig.objects.get(tenant=self.neuron)
        self.assertFalse(config.is_active)
        self.assertFalse(config.recipients.exists())

    def test_skips_when_user_not_member(self):
        seed(django_apps, None)
        self.assertFalse(CardTopupNotifyConfig.objects.exists())

    def test_skips_when_membership_inactive(self):
        TenantMembership.objects.create(tenant=self.neuron, user=self.user18, is_active=False)
        seed(django_apps, None)
        self.assertFalse(CardTopupNotifyConfig.objects.exists())

    def test_other_tenants_untouched(self):
        other = Tenant.objects.create(name="Aqua", subdomain="lemonaqua", is_active=True)
        TenantMembership.objects.create(tenant=other, user=self.user18, is_active=True)
        seed(django_apps, None)
        self.assertFalse(CardTopupNotifyConfig.objects.exists())

    def test_missing_tenant_is_skipped(self):
        Tenant.objects.filter(pk=self.neuron.pk).delete()
        seed(django_apps, None)
        self.assertFalse(CardTopupNotifyConfig.objects.exists())
