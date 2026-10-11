"""
Tests for link_payroll_requests_to_documents: explicit request -> payroll
document linking, with optional request-amount fix from the document total.
"""

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.modules.payroll.models import PayrollDocument, PayrollLine
from apps.modules.requests.models import Request, RequestComment
from apps.modules.requests.payroll_request_document_linking import link_payroll_requests_to_documents
from apps.tenants.models import Tenant

User = get_user_model()


class LinkPayrollRequestsToDocumentsTests(TestCase):
    def setUp(self):
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="system-link-payroll", password="x", full_name="Система")
        self.tenant = Tenant.objects.create(name="Acme", subdomain="acme-link-payroll", is_active=True)
        self.other_tenant = Tenant.objects.create(name="Other", subdomain="other-link-payroll", is_active=True)
        self.admin = User.objects.create_user(username="admin-link-payroll", password="x")

    def _doc(self, *, doc_id, total, tenant=None):
        doc = PayrollDocument.objects.create(tenant=tenant or self.tenant, doc_id=doc_id)
        PayrollLine.objects.create(
            document=doc, line_no=1, employee="E", item="Salary", description="", sum=Decimal(total),
        )
        return doc

    def _request(self, *, amount, expense_id, status=Request.STATUS_PAYED, expense_ref_id=None):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.admin,
            requester=self.admin,
            title="ЗП",
            description="",
            amount=Decimal(amount),
            currency="UZS",
            payment_type=Request.PAYMENT_TYPE_PAYROLL,
            urgency=Request.URGENCY_NORMAL,
            billing_date=date(2026, 7, 1),
            expense_id=expense_id,
            expense_ref_id=expense_ref_id,
            expense_ref_target=Request.EXPENSE_REF_TARGET_PAYROLL if expense_ref_id else None,
            status=status,
            payed_at=20260713 if status == Request.STATUS_PAYED else None,
        )

    def test_wrong_doc_number_with_equal_total_is_linked_and_number_fixed(self):
        doc = self._doc(doc_id="1-000000077", total="7000000.00")
        req = self._request(amount="7000000.00", expense_id="1-000000541")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant, pairs=[(req.id, "1-000000077")], set_amount_from_document=False, apply_changes=True,
        )

        self.assertEqual([o.outcome for o in outcomes], ["linked"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, doc.id)
        self.assertEqual(req.expense_ref_target, Request.EXPENSE_REF_TARGET_PAYROLL)
        self.assertEqual(req.expense_id, "1-000000077")
        self.assertEqual(req.amount, Decimal("7000000.00"))
        comment = RequestComment.objects.get(request_id=req.pk)
        self.assertEqual(comment.created_by_id, 1)
        self.assertIn("1-000000541", comment.body)

    def test_amount_mismatch_is_refused_without_flag(self):
        self._doc(doc_id="1-000000073", total="18450000.00")
        req = self._request(amount="18540000.00", expense_id="1-000000073")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant, pairs=[(req.id, "1-000000073")], set_amount_from_document=False, apply_changes=True,
        )

        self.assertEqual([o.outcome for o in outcomes], ["error"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
        self.assertEqual(req.amount, Decimal("18540000.00"))

    def test_amount_mismatch_with_flag_fixes_amount_and_comments_old_value(self):
        doc = self._doc(doc_id="1-000000073", total="18450000.00")
        req = self._request(amount="18540000.00", expense_id="1-000000073")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant, pairs=[(req.id, "1-000000073")], set_amount_from_document=True, apply_changes=True,
        )

        self.assertEqual([o.outcome for o in outcomes], ["linked_amount_fixed"])
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, doc.id)
        self.assertEqual(req.amount, Decimal("18450000.00"))
        self.assertIn("18540000", RequestComment.objects.get(request_id=req.pk).body)

    def test_dry_run_does_not_write(self):
        self._doc(doc_id="1-000000084", total="14739000.00")
        req = self._request(amount="14739000.00", expense_id="1-000000596")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant, pairs=[(req.id, "1-000000084")], set_amount_from_document=True, apply_changes=False,
        )

        self.assertEqual([o.outcome for o in outcomes], ["linked"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)
        self.assertEqual(req.expense_id, "1-000000596")
        self.assertFalse(RequestComment.objects.filter(request_id=req.pk).exists())

    def test_document_claimed_by_rejected_request_is_still_available(self):
        doc = self._doc(doc_id="1-000000096", total="11696000.00")
        self._request(amount="11696000.00", expense_id=None, status=Request.STATUS_REJECTED, expense_ref_id=doc.id)
        req = self._request(amount="11696000.00", expense_id="1-0000000961")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant, pairs=[(req.id, "1-000000096")], set_amount_from_document=False, apply_changes=True,
        )

        self.assertEqual([o.outcome for o in outcomes], ["linked"])

    def test_document_claimed_by_live_request_is_refused(self):
        doc = self._doc(doc_id="1-000000094", total="13846000.00")
        self._request(amount="13846000.00", expense_id="1-000000094", expense_ref_id=doc.id)
        req = self._request(amount="14119000.00", expense_id="1-000000094")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant, pairs=[(req.id, "1-000000094")], set_amount_from_document=True, apply_changes=True,
        )

        self.assertEqual([o.outcome for o in outcomes], ["error"])
        req.refresh_from_db()
        self.assertIsNone(req.expense_ref_id)

    def test_already_linked_or_foreign_tenant_document_is_refused(self):
        self._doc(doc_id="FOREIGN-1", total="100.00", tenant=self.other_tenant)
        linked_doc = self._doc(doc_id="1-000000001", total="100.00")
        linked = self._request(amount="100.00", expense_id="1-000000001", expense_ref_id=linked_doc.id)
        free = self._request(amount="100.00", expense_id="x")

        outcomes = link_payroll_requests_to_documents(
            tenant=self.tenant,
            pairs=[(linked.id, "1-000000001"), (free.id, "FOREIGN-1")],
            set_amount_from_document=True,
            apply_changes=True,
        )

        self.assertEqual([o.outcome for o in outcomes], ["error", "error"])

    def test_command_parses_pairs_and_applies(self):
        doc = self._doc(doc_id="1-000000077", total="7000000.00")
        req = self._request(amount="7000000.00", expense_id="1-000000541")

        out = StringIO()
        call_command(
            "link_payroll_requests_to_documents", tenant=self.tenant.subdomain, pair=[f"{req.id}:1-000000077"],
            stdout=out,
        )
        self.assertIn("Would link: 1", out.getvalue())

        call_command(
            "link_payroll_requests_to_documents", tenant=str(self.tenant.id), pair=[f"{req.id}:1-000000077"],
            apply=True, stdout=StringIO(),
        )
        req.refresh_from_db()
        self.assertEqual(req.expense_ref_id, doc.id)

    def test_command_rejects_malformed_pair(self):
        with self.assertRaises(CommandError):
            call_command("link_payroll_requests_to_documents", tenant=self.tenant.subdomain, pair=["abc"])
