"""
Tests for expense_vendor_name_matching — generalized (tenant-agnostic)
version of the exact-normalized-name vendor lookup originally written as a
Lemonfit Aqua-only one-off.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.modules.requests.expense_vendor_name_matching import (
    build_vendor_name_index,
    normalize_vendor_name,
    resolve_vendor_id_from_index,
)
from apps.modules.vendors.models import Vendor
from apps.tenants.models import Tenant

User = get_user_model()


class NormalizeVendorNameTests(TestCase):
    def test_strips_legal_entity_tokens_and_quotes(self):
        self.assertEqual(normalize_vendor_name('ООО "Gevorkyan Trade"'), "GEVORKYAN TRADE")

    def test_uppercases_and_collapses_whitespace(self):
        self.assertEqual(normalize_vendor_name("  acme   corp  "), "ACME CORP")

    def test_empty_and_none(self):
        self.assertEqual(normalize_vendor_name(""), "")
        self.assertEqual(normalize_vendor_name(None), "")


class VendorNameIndexTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-vendor-idx", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Other", subdomain="other-vendor-idx", is_active=True)
        self.admin = User.objects.create_user(username="admin-vendor-idx", password="x")

    def _make_vendor(self, *, tenant, name, kind=Vendor.KIND_TRANSFER):
        return Vendor.objects.create(tenant=tenant, kind=kind, name=name, created_by=self.admin)

    def test_index_groups_by_normalized_name(self):
        vendor = self._make_vendor(tenant=self.tenant, name='ООО "Gevorkyan Trade"')

        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        self.assertEqual(index.get("GEVORKYAN TRADE"), [vendor.id])

    def test_index_scoped_to_kind(self):
        self._make_vendor(tenant=self.tenant, name="Same Name", kind=Vendor.KIND_CASH)

        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        self.assertNotIn("SAME NAME", index)

    def test_index_scoped_to_tenant(self):
        self._make_vendor(tenant=self.other_tenant, name="Cross Tenant Vendor")

        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        self.assertEqual(index, {})

    def test_resolve_returns_id_for_unique_match(self):
        vendor = self._make_vendor(tenant=self.tenant, name="Acme LLC")
        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        resolved = resolve_vendor_id_from_index("acme llc", index)

        self.assertEqual(resolved, vendor.id)

    def test_resolve_returns_none_for_ambiguous_match(self):
        self._make_vendor(tenant=self.tenant, name='ООО "Acme"')
        self._make_vendor(tenant=self.tenant, name='MCHJ "Acme"')
        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        self.assertIsNone(resolve_vendor_id_from_index("acme", index))

    def test_resolve_returns_none_for_no_match(self):
        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        self.assertIsNone(resolve_vendor_id_from_index("Nonexistent", index))

    def test_resolve_returns_none_for_empty_text(self):
        index = build_vendor_name_index(tenant_id=self.tenant.id, kind=Vendor.KIND_TRANSFER)

        self.assertIsNone(resolve_vendor_id_from_index("", index))
