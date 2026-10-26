"""
Tests for align_payment_purposes: one categories/purposes dictionary across
tenants from a JSON plan, with renames rewriting request history.
"""

import json
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from apps.modules.requests.models import (
    AutoRequestTemplate,
    Request,
    RequestApprovalConfig,
    RequestApprovalPaymentTypeConfig,
    RequestApprovalPurposeExceptionConfig,
    RequestApprovalPurposeExceptionPurpose,
    RequestCategory,
    RequestComment,
    RequestFormConfig,
    RequestFormPaymentTypeConfig,
    RequestPaymentPurposeConfig,
)
from apps.modules.requests.payment_purpose_alignment import PlanError, align_tenant, load_plan, parse_plan
from apps.tenants.models import Tenant

User = get_user_model()

CASH = Request.PAYMENT_TYPE_CASH


class AlignPaymentPurposesTests(TestCase):
    def setUp(self):
        if not User.objects.filter(pk=1).exists():
            User.objects.create_user(username="system-align-purposes", password="x", full_name="Система")
        self.system = User.objects.get(pk=1)
        self.tenant = Tenant.objects.create(name="Club", subdomain="club-align-purposes", is_active=True)
        self.user = User.objects.create_user(username="user-align-purposes", password="x")
        form_config = RequestFormConfig.objects.create(tenant=self.tenant)
        self.cash_cfg = RequestFormPaymentTypeConfig.objects.create(config=form_config, payment_type=CASH)

    def _plan(self, **overrides):
        data = {
            "tenants": [str(self.tenant.id)],
            "categories": ["Содержание клуба", "Прочие расходы"],
            "purposes": {
                CASH: [["Ремонтные работы", "Содержание клуба"], ["Мероприятие", "Прочие расходы"]],
            },
        }
        data.update(overrides)
        return parse_plan(data)

    def _purpose(self, name, *, category="Содержание клуба", is_active=True):
        return RequestPaymentPurposeConfig.objects.create(
            payment_type_config=self.cash_cfg, name=name, category=category, is_active=is_active,
        )

    def _request(self, purpose, *, status=Request.STATUS_PAYED, category="Содержание клуба"):
        return Request.objects.create(
            tenant=self.tenant,
            created_by=self.user,
            requester=self.user,
            title="R",
            description="",
            amount=100,
            payment_type=CASH,
            payment_purpose=purpose,
            category=category,
            billing_date=date(2026, 10, 1),
            status=status,
        )

    def _align(self, plan, *, apply_changes=True):
        return align_tenant(tenant=self.tenant, tenant_ref=str(self.tenant.id), plan=plan, apply_changes=apply_changes)

    def _names(self, *, is_active=True):
        return set(
            RequestPaymentPurposeConfig.objects.filter(
                payment_type_config=self.cash_cfg, is_active=is_active,
            ).values_list("name", flat=True)
        )

    def test_dry_run_reports_but_changes_nothing(self):
        self._purpose("Лишнее")
        req = self._request("Мироприятие")
        plan = self._plan(renames=[{"payment_type": CASH, "from": ["Мироприятие"], "to": "Мероприятие"}])

        report = self._align(plan, apply_changes=False)

        self.assertTrue(report.changes)
        self.assertEqual(report.requests_rewritten, 1)
        self.assertEqual(self._names(), {"Лишнее"})
        self.assertFalse(RequestCategory.objects.filter(tenant=self.tenant).exists())
        req.refresh_from_db()
        self.assertEqual(req.payment_purpose, "Мироприятие")
        self.assertFalse(RequestComment.objects.filter(request=req).exists())

    def test_apply_adds_activates_deactivates_and_fixes_category_without_deleting(self):
        self._purpose("Ремонтные работы", category="Прочие расходы", is_active=False)
        self._purpose("Лишнее")
        RequestCategory.objects.create(tenant=self.tenant, name="Старая", is_active=True)

        self._align(self._plan())

        self.assertEqual(self._names(), {"Ремонтные работы", "Мероприятие"})
        self.assertEqual(self._names(is_active=False), {"Лишнее"})
        repair = RequestPaymentPurposeConfig.objects.get(payment_type_config=self.cash_cfg, name="Ремонтные работы")
        self.assertEqual(repair.category, "Содержание клуба")
        active_categories = set(
            RequestCategory.objects.filter(tenant=self.tenant, is_active=True).values_list("name", flat=True)
        )
        self.assertEqual(active_categories, {"Содержание клуба", "Прочие расходы"})
        self.assertTrue(RequestCategory.objects.filter(tenant=self.tenant, name="Старая", is_active=False).exists())

    def test_rename_rewrites_history_templates_default_and_keeps_exception_link(self):
        typo = self._purpose("Мироприятие", category="Прочие расходы")
        self.cash_cfg.default_payment_purpose = "Мироприятие"
        self.cash_cfg.save(update_fields=["default_payment_purpose"])
        approval_pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=RequestApprovalConfig.objects.create(tenant=self.tenant), payment_type=CASH,
        )
        exception = RequestApprovalPurposeExceptionConfig.objects.create(payment_type_config=approval_pt, name="exc")
        RequestApprovalPurposeExceptionPurpose.objects.create(exception_config=exception, payment_purpose=typo)
        template = AutoRequestTemplate.objects.create(
            tenant=self.tenant, payment_type=CASH, payment_purpose="Мироприятие", requester=self.user,
        )
        paid = self._request("Мироприятие")
        deleted = self._request("Мирприятие", status=Request.STATUS_DELETED)
        other = self._request("Ремонтные работы")
        plan = self._plan(renames=[{"payment_type": CASH, "from": ["Мироприятие", "Мирприятие"], "to": "Мероприятие"}])

        report = self._align(plan)

        typo.refresh_from_db()
        self.assertEqual(typo.name, "Мероприятие")
        self.assertTrue(typo.is_active)
        self.assertTrue(RequestApprovalPurposeExceptionPurpose.objects.filter(payment_purpose=typo).exists())
        self.cash_cfg.refresh_from_db()
        self.assertEqual(self.cash_cfg.default_payment_purpose, "Мероприятие")
        template.refresh_from_db()
        self.assertEqual(template.payment_purpose, "Мероприятие")
        for req in (paid, deleted):
            req = Request.all_objects.get(pk=req.pk)
            self.assertEqual(req.payment_purpose, "Мероприятие")
            comment = RequestComment.objects.get(request=req)
            self.assertEqual(comment.created_by_id, self.system.pk)
            self.assertIn("«Мероприятие»", comment.body)
        other.refresh_from_db()
        self.assertEqual(other.payment_purpose, "Ремонтные работы")
        self.assertFalse(RequestComment.objects.filter(request=other).exists())
        self.assertEqual(report.requests_rewritten, 2)

    def test_rename_into_existing_purpose_deactivates_old_and_moves_exception_link(self):
        old = self._purpose("Мироприятие", category="Прочие расходы")
        new = self._purpose("Мероприятие", category="Прочие расходы")
        approval_pt = RequestApprovalPaymentTypeConfig.objects.create(
            config=RequestApprovalConfig.objects.create(tenant=self.tenant), payment_type=CASH,
        )
        exception = RequestApprovalPurposeExceptionConfig.objects.create(payment_type_config=approval_pt, name="exc")
        link = RequestApprovalPurposeExceptionPurpose.objects.create(exception_config=exception, payment_purpose=old)

        self._align(self._plan(renames=[{"payment_type": CASH, "from": ["Мироприятие"], "to": "Мероприятие"}]))

        old.refresh_from_db()
        self.assertFalse(old.is_active)
        link.refresh_from_db()
        self.assertEqual(link.payment_purpose_id, new.pk)

    def test_request_move_sets_purpose_and_plan_category_and_skips_mismatch(self):
        moved = self._request("Аутсерс услуги", category="Содержание клуба")
        changed_meanwhile = self._request("Ремонтные работы")
        plan = self._plan(request_moves=[
            {"tenant": str(self.tenant.id), "request_id": moved.pk, "payment_type": CASH,
             "from": "Аутсерс услуги", "to": "Мероприятие"},
            {"tenant": str(self.tenant.id), "request_id": changed_meanwhile.pk, "payment_type": CASH,
             "from": "Аутсерс услуги", "to": "Мероприятие"},
        ])

        report = self._align(plan)

        moved.refresh_from_db()
        self.assertEqual((moved.payment_purpose, moved.category), ("Мероприятие", "Прочие расходы"))
        self.assertIn("«Аутсерс услуги» → «Мероприятие»", RequestComment.objects.get(request=moved).body)
        changed_meanwhile.refresh_from_db()
        self.assertEqual(changed_meanwhile.payment_purpose, "Ремонтные работы")
        self.assertTrue(any(f"#{changed_meanwhile.pk}" in w for w in report.warnings))

    def test_second_apply_is_a_no_op(self):
        self._purpose("Мироприятие", category="Прочие расходы")
        req = self._request("Аутсерс услуги")
        plan = self._plan(
            renames=[{"payment_type": CASH, "from": ["Мироприятие"], "to": "Мероприятие"}],
            request_moves=[{"tenant": str(self.tenant.id), "request_id": req.pk, "payment_type": CASH,
                            "from": "Аутсерс услуги", "to": "Ремонтные работы"}],
        )
        self._align(plan)

        report = self._align(plan)

        self.assertEqual(report.changes, [])
        self.assertEqual(report.warnings, [])
        self.assertEqual(RequestComment.objects.filter(request=req).count(), 1)

    def test_command_dry_run_prints_report(self):
        self._purpose("Лишнее")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text(json.dumps({
                "tenants": [self.tenant.subdomain],
                "categories": ["Содержание клуба"],
                "purposes": {CASH: [["Ремонтные работы", "Содержание клуба"]]},
            }), encoding="utf-8")
            out = StringIO()
            call_command("align_payment_purposes", f"--plan={path}", stdout=out)

        self.assertIn("отключено «Лишнее»", out.getvalue())
        self.assertIn("Dry run complete", out.getvalue())
        self.assertEqual(self._names(), {"Лишнее"})


class PurposeAlignmentPlanTests(TestCase):
    def test_lemonfit_plan_is_consistent(self):
        plan = load_plan("lemonfit_2026_10")

        self.assertEqual(plan.tenants, ("1", "3", "7"))
        self.assertEqual(len(plan.categories), 16)
        counts = {pt: len(plan.purposes_for(pt)) for pt in {p.payment_type for p in plan.purposes}}
        self.assertEqual(counts, {
            Request.PAYMENT_TYPE_CASH: 29,
            Request.PAYMENT_TYPE_PAYROLL: 3,
            Request.PAYMENT_TYPE_TRANSFER: 30,
            Request.PAYMENT_TYPE_CARD: 7,
            Request.PAYMENT_TYPE_TOPUP: 1,
        })
        self.assertEqual({m.request_id for m in plan.request_moves}, {6572, 6574, 8664, 8849})

    def test_purpose_with_unknown_category_is_rejected(self):
        with self.assertRaises(PlanError):
            parse_plan({"tenants": ["1"], "categories": ["A"], "purposes": {CASH: [["X", "B"]]}})

    def test_move_to_purpose_outside_plan_is_rejected(self):
        with self.assertRaises(PlanError):
            parse_plan({
                "tenants": ["1"],
                "categories": ["A"],
                "purposes": {CASH: [["X", "A"]]},
                "request_moves": [{"tenant": "1", "request_id": 1, "payment_type": CASH, "from": "Y", "to": "Z"}],
            })

    def test_unknown_payment_type_is_rejected(self):
        with self.assertRaises(PlanError):
            parse_plan({"tenants": ["1"], "categories": ["A"], "purposes": {"Бартер": [["X", "A"]]}})
