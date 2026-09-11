"""Tests for the fix_lemonaqua_misselected_vendor_requests one-off command."""

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
    call_command("fix_lemonaqua_misselected_vendor_requests", stdout=out, **options)
    return out.getvalue()


class FixLemonaquaMisselectedVendorRequestsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(id=3, name="Lemonfit Aqua", subdomain="lemonaqua-vendorfixtest", is_active=True)
        self.admin = User.objects.create_user(username="admin-vendorfix", password="x")

        self.treasury = Vendor.objects.create(
            id=91, tenant=self.tenant, kind=Vendor.KIND_TRANSFER,
            name='Ўзбекистон Республикаси Молия вазирлиги Казначилиги', created_by=self.admin,
        )
        self.dsi = Vendor.objects.create(
            id=92, tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Mirzo-Ulug'bek Tumani DSI",
            created_by=self.admin,
        )
        self.fitline_payroll = Vendor.objects.create(
            id=93, tenant=self.tenant, kind=Vendor.KIND_TRANSFER,
            name='20*ООО "FITLINE FITNESS CENTER GROUP" Тран счет для зачис ПК на З/П', created_by=self.admin,
        )

        self.req_salary = Request.objects.create(
            id=7936, tenant=self.tenant, created_by=self.admin, requester=self.admin,
            title="Lemonfit Aqua", description="", amount=Decimal("5720000.00"), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1), vendor_ref=self.treasury, expense_id="",
            status=Request.STATUS_PAYED, payed_at=20260903,
        )
        self.req_pension = Request.objects.create(
            id=8021, tenant=self.tenant, created_by=self.admin, requester=self.admin,
            title="Lemonfit Aqua", description="", amount=Decimal("6500.00"), currency="UZS",
            payment_type=Request.PAYMENT_TYPE_TRANSFER, urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 9, 1), vendor_ref=self.treasury, expense_id="",
            status=Request.STATUS_PAYED, payed_at=20260909,
        )

    def test_dry_run_makes_no_changes(self):
        output = _run()

        self.req_salary.refresh_from_db()
        self.req_pension.refresh_from_db()
        self.assertEqual(self.req_salary.vendor_ref_id, 91)
        self.assertEqual(self.req_pension.vendor_ref_id, 91)
        self.assertIn("Would fix: 2", output)
        self.assertIn("Dry run complete", output)

    def test_apply_fixes_both_requests(self):
        output = _run(apply=True)

        self.req_salary.refresh_from_db()
        self.req_pension.refresh_from_db()
        self.assertEqual(self.req_salary.vendor_ref_id, 93)
        self.assertEqual(self.req_pension.vendor_ref_id, 92)
        self.assertIn("Fixed: 2", output)

    def test_apply_is_idempotent(self):
        _run(apply=True)
        output = _run(apply=True)

        self.assertIn("Fixed: 0", output)
        self.assertIn("Already correct: 2", output)

    def test_unexpected_current_vendor_is_skipped_not_overwritten(self):
        other_vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="Someone else", created_by=self.admin,
        )
        Request.objects.filter(pk=7936).update(vendor_ref=other_vendor)

        output = _run(apply=True)

        self.req_salary.refresh_from_db()
        self.assertEqual(self.req_salary.vendor_ref_id, other_vendor.id)
        self.assertIn("Skipped (1)", output)
        self.assertIn("unexpected state", output)
