"""search_everywhere: one substring/number/date search over every source the user may see.

The Telegram assistant looked for request 9003 with list_requests(search="9003"),
which only searches description and payment purpose, and found nothing.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.mcp_server.tools import search as search_tools
from apps.mcp_server.tools.search import SearchSource


class SearchEverywhereTests(TestCase):
    def setUp(self):
        from apps.modules.requests.models import Request, RequestComment
        from apps.modules.vendors.models import Vendor
        from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

        User = get_user_model()
        self.tenant = Tenant.objects.create(name="Acme", subdomain="srch", is_active=True, mcp_enabled=True)
        for key in ("requests", "vendors", "tasks", "notes", "cash"):
            TenantModuleConfig.objects.create(tenant=self.tenant, module_key=key, is_enabled=True)

        def member(username, role, **kw):
            user = User.objects.create_user(username=username, password="x", **kw)
            TenantMembership.objects.create(user=user, tenant=self.tenant, is_active=True)
            TenantUserRole.objects.create(tenant=self.tenant, user=user, role=role)
            return user

        self.admin = member("srch_admin", TenantUserRole.ROLE_ADMIN)
        self.requester = member("srch_req", TenantUserRole.ROLE_REQUESTER, first_name="Алишер")

        def make_request(**kw):
            defaults = dict(
                tenant=self.tenant, created_by=self.requester, requester=self.requester,
                category="Ремонт", amount=Decimal("21005000"), currency="UZS",
                status=Request.STATUS_APPROVED, billing_date=date(2026, 1, 15),
            )
            defaults.update(kw)
            return Request.objects.create(**defaults)

        self.req = make_request(description="Гипсокартон, строй материалы")
        self.comment = RequestComment.objects.create(
            request=self.req, created_by=self.admin, body="Оплатить до пятницы",
        )
        self.deleted = make_request(description="Гипсокартон удалённый", status=Request.STATUS_DELETED)
        RequestComment.objects.create(request=self.deleted, created_by=self.admin, body="Пятница, удалённая")
        self.vendor = Vendor.objects.create(
            tenant=self.tenant, kind=Vendor.KIND_TRANSFER, name="ООО Гипс Трейд", inn="305123456",
            created_by=self.admin,
        )

        other = Tenant.objects.create(name="Other", subdomain="srch2", is_active=True, mcp_enabled=True)
        make_request(tenant=other, description="Гипсокартон чужой")

    def _search(self, user, query, **kw):
        with patch("apps.mcp_server.tools.search.require_member", return_value=(user, self.tenant)):
            return search_tools.search_everywhere(self.tenant.id, query, **kw)

    @staticmethod
    def _group(result, kind):
        return next((g for g in result["groups"] if g["type"] == kind), None)

    def test_number_finds_request_by_id(self):
        result = self._search(self.admin, f"№{self.req.id}")
        items = self._group(result, "request")["items"]
        hit = next(i for i in items if i["id"] == self.req.id)
        self.assertIn({"field": "id", "value": str(self.req.id)}, hit["matched"])

    def test_amount_with_spaces_matches_amount_field(self):
        result = self._search(self.admin, "21 005 000")
        hit = self._group(result, "request")["items"][0]
        self.assertEqual(hit["id"], self.req.id)
        self.assertIn("amount", [m["field"] for m in hit["matched"]])

    def test_substring_of_any_field_case_insensitive(self):
        result = self._search(self.admin, "гипсокартон")
        self.assertEqual([i["id"] for i in self._group(result, "request")["items"]], [self.req.id])
        vendor = self._search(self.admin, "305123")
        self.assertEqual(self._group(vendor, "vendor")["items"][0]["id"], self.vendor.id)

    def test_comment_match_points_to_parent_request(self):
        result = self._search(self.admin, "пятниц")
        group = self._group(result, "request_comment")
        self.assertEqual(group["total"], 1)  # the deleted request's comment is hidden
        self.assertEqual(group["items"][0]["parent"], {"type": "request", "id": self.req.id})
        self.assertEqual(group["items"][0]["title"], "Оплатить до пятницы")

    def test_linked_person_name_is_searched(self):
        result = self._search(self.admin, "алишер")
        hit = self._group(result, "request")["items"][0]
        self.assertIn("requester__first_name", [m["field"] for m in hit["matched"]])

    def test_date_matches_date_fields(self):
        result = self._search(self.admin, "15.01.2026")
        hit = self._group(result, "request")["items"][0]
        self.assertIn({"field": "billing_date", "value": "2026-01-15"}, hit["matched"])

    def test_requester_has_no_cash_and_sees_only_own_tasks_and_notes(self):
        from apps.modules.notes.models import Note
        from apps.modules.tasks.models import Task

        now = timezone.now()
        Task.objects.create(
            tenant=self.tenant, assignee=self.admin, created_by=self.admin, title="Сверка Гипс",
            last_edit_by=self.admin, last_edit_at=now,
        )
        own = Task.objects.create(
            tenant=self.tenant, assignee=self.requester, created_by=self.admin, title="Гипс замер",
            last_edit_by=self.admin, last_edit_at=now,
        )
        Note.objects.create(
            tenant=self.tenant, created_by=self.admin, recipient_user=self.admin,
            target_type=Note.TARGET_REQUEST, target_id=self.req.id, message="Гипс личное",
        )

        result = self._search(self.requester, "гипс")
        self.assertIn("cash_expense", result["not_searched_no_access"])
        self.assertIn("budget", result["not_searched_no_access"])  # module disabled
        self.assertEqual([i["id"] for i in self._group(result, "task")["items"]], [own.id])
        self.assertIsNone(self._group(result, "note"))

        admin_result = self._search(self.admin, "гипс")
        self.assertEqual(self._group(admin_result, "task")["total"], 2)
        self.assertEqual(self._group(admin_result, "note")["total"], 1)

    def test_deprecated_invest_company_type_matches_nothing(self):
        only_deprecated = self._search(self.admin, "гипс", types="invest_company")
        self.assertEqual(only_deprecated["groups"], [])
        self.assertEqual(only_deprecated.get("not_searched_no_access", []), [])

        mixed = self._search(self.admin, "гипс", types="invest_company,vendor")
        self.assertEqual(mixed, self._search(self.admin, "гипс", types="vendor"))
        self.assertEqual([g["type"] for g in mixed["groups"]], ["vendor"])
        self.assertNotIn("invest_company", search_tools.SOURCE_KINDS)

    def test_types_filter_and_validation(self):
        result = self._search(self.admin, "гипс", types="vendor")
        self.assertEqual([g["type"] for g in result["groups"]], ["vendor"])
        with self.assertRaisesRegex(ValueError, "Unknown types: nope"):
            self._search(self.admin, "гипс", types="nope")
        with self.assertRaisesRegex(ValueError, "at least 2 characters"):
            self._search(self.admin, "г")

    def test_failing_source_is_reported_and_others_still_searched(self):
        sources = (
            SearchSource("broken", "apps.modules.nope.models.Missing", "requests"),
            SearchSource("vendor", "apps.modules.vendors.models.Vendor", "vendors"),
        )
        with patch.object(search_tools, "SOURCES", sources), self.assertLogs(search_tools.logger, "ERROR"):
            result = self._search(self.admin, "гипс")
        self.assertEqual(result["failed"], ["broken"])
        self.assertEqual(self._group(result, "vendor")["total"], 1)


class SearchFieldDiscoveryTests(TestCase):
    def test_secrets_and_tenant_name_title_are_not_searched(self):
        from apps.modules.requests.models import Approval, Request

        approval = search_tools._discover_fields(Approval, SearchSource("a", "", "requests"))
        self.assertIn("comment", approval.text)
        self.assertNotIn("resend_key", approval.text)

        request_source = next(s for s in search_tools.SOURCES if s.kind == "request")
        request = search_tools._discover_fields(Request, request_source)
        self.assertNotIn("title", request.text)
        self.assertNotIn("tenant__name", request.text)
        self.assertIn("description", request.text)

    def test_every_source_model_imports(self):
        from django.utils.module_loading import import_string

        for source in search_tools.SOURCES:
            model = import_string(source.model_path)
            model._meta.get_field(source.tenant_lookup.split("__")[0])

    def test_parse_query(self):
        parse = search_tools.parse_query
        self.assertEqual(parse("#9003").number, Decimal("9003"))
        self.assertEqual(parse("21 005 000,50").number, Decimal("21005000.50"))
        self.assertIsNone(parse("ООО 9003").number)
        self.assertEqual(parse("2026-11-05").day, date(2026, 11, 5))
        self.assertIsNone(parse("2026-11-05").number)
