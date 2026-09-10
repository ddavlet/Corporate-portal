"""Tests for the merge_lemonaqua_duplicate_vendors one-off command."""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.requests.models import Request
from apps.modules.vendors.models import Vendor
from apps.tenants.models import Tenant

User = get_user_model()


def _run(**options):
    out = StringIO()
    call_command("merge_lemonaqua_duplicate_vendors", stdout=out, **options)
    return out.getvalue()


class MergeLemonaquaDuplicateVendorsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-mergetest", is_active=True)
        self.admin = User.objects.create_user(username="admin-merge", password="x")

        self.don_non_old = Vendor.objects.create(
            id=67, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="DON-NON", created_by=self.admin,
        )
        self.don_non_new = Vendor.objects.create(
            id=82, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name='"DON-NON" MCHJ', created_by=self.admin,
        )
        self.telecom_old = Vendor.objects.create(
            id=83, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name='"O`ZBEKTELEKOM" AJ', created_by=self.admin,
        )
        self.telecom_new = Vendor.objects.create(
            id=135, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name='"O`ZBEKTELEKOM " AJ', created_by=self.admin,
        )
        self.murodov_old = Vendor.objects.create(
            id=623, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="MURODOV DILSHOD DOLIM O'G'LI",
            created_by=self.admin,
        )
        self.murodov_new = Vendor.objects.create(
            id=641, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="ЯТТ MURODOV DILSHOD DOLIM O'G'LI",
            created_by=self.admin,
        )
        self.fire_old = Vendor.objects.create(
            id=800, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="AUTOMATIC FIRE SYSTEM", created_by=self.admin,
        )
        self.fire_new = Vendor.objects.create(
            id=801, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name='"AUTOMATIC FIRE SYSTEM" MCHJ',
            created_by=self.admin,
        )
        self.aroma_old = Vendor.objects.create(
            id=110, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="AROMA HOUSE", created_by=self.admin,
        )
        self.aroma_new = Vendor.objects.create(
            id=145, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name='"AROMA HOUSE" MCHJ', created_by=self.admin,
        )

        self.req_don_non_1 = self._make_request(id=7999, vendor=self.don_non_old, amount="20000000.00")
        self.req_don_non_2 = self._make_request(id=1897, vendor=self.don_non_old, amount="9944000.00")
        self.req_telecom = self._make_request(id=7878, vendor=self.telecom_old, amount="1500000.00")
        self.req_murodov = self._make_request(id=7853, vendor=self.murodov_old, amount="10500000.00")
        self.req_fire = self._make_request(id=8009, vendor=self.fire_old, amount="1056706.00")
        self.req_aroma = self._make_request(id=7964, vendor=self.aroma_old, amount="2312000.00")

    def _make_request(self, *, id, vendor, amount):
        return Request.objects.create(
            id=id,
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Lemonfit Aqua",
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1),
            vendor_ref=vendor,
            expense_id="",
            status=Request.STATUS_PAYED,
            payed_at=20260909,
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.req_don_non_1.refresh_from_db()
        self.req_telecom.refresh_from_db()
        self.req_murodov.refresh_from_db()
        self.req_fire.refresh_from_db()
        self.req_aroma.refresh_from_db()
        self.assertEqual(self.req_don_non_1.vendor_ref_id, 67)
        self.assertEqual(self.req_telecom.vendor_ref_id, 83)
        self.assertEqual(self.req_murodov.vendor_ref_id, 623)
        self.assertEqual(self.req_fire.vendor_ref_id, 800)
        self.assertEqual(self.req_aroma.vendor_ref_id, 110)
        self.assertIn("Would repoint: 6", output)
        self.assertIn("Dry run complete", output)

    def test_apply_repoints_all_requests_for_each_merge_pair(self):
        output = _run(apply=True)

        self.req_don_non_1.refresh_from_db()
        self.req_don_non_2.refresh_from_db()
        self.req_telecom.refresh_from_db()
        self.req_murodov.refresh_from_db()
        self.req_fire.refresh_from_db()
        self.req_aroma.refresh_from_db()
        self.assertEqual(self.req_don_non_1.vendor_ref_id, 82)
        self.assertEqual(self.req_don_non_2.vendor_ref_id, 82)
        self.assertEqual(self.req_telecom.vendor_ref_id, 135)
        self.assertEqual(self.req_murodov.vendor_ref_id, 641)
        self.assertEqual(self.req_fire.vendor_ref_id, 801)
        self.assertEqual(self.req_aroma.vendor_ref_id, 145)
        self.assertIn("Repointed: 6", output)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Repointed: 0", output)

    def test_does_not_touch_other_tenants(self):
        other_tenant = Tenant.objects.create(name="Other", subdomain="other-mergetest", is_active=True)
        other_vendor = Vendor.objects.create(
            id=6700, tenant=other_tenant, kind=Vendor.KIND_TRANSFER, name="DON-NON", created_by=self.admin,
        )
        other_request = Request.objects.create(
            tenant=other_tenant,
            created_by=self.admin,
            requester=self.admin,
            title="Other tenant",
            description="",
            amount=Decimal("1000.00"),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1),
            vendor_ref=other_vendor,
            expense_id="",
            status=Request.STATUS_PAYED,
            payed_at=20260909,
        )

        _run(apply=True)

        other_request.refresh_from_db()
        self.assertEqual(other_request.vendor_ref_id, other_vendor.id)

    def test_skips_merge_pair_when_new_vendor_missing(self):
        Vendor.objects.filter(pk=135).delete()

        output = _run(apply=True)

        self.req_telecom.refresh_from_db()
        self.assertEqual(self.req_telecom.vendor_ref_id, 83)
        self.assertIn("Skipped (1)", output)
        self.assertIn("new vendor 135 not found", output)
