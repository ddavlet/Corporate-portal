from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.tasks.models import Task, TaskComment
from apps.tenants.models import Tenant, TenantMembership, TenantModuleConfig, TenantUserRole

User = get_user_model()

HOST = "acme.example.com"


def _setup_tenant(subdomain="acme", module_key="tasks"):
    tenant = Tenant.objects.create(name="Acme", subdomain=subdomain, is_active=True)
    TenantModuleConfig.objects.create(tenant=tenant, module_key=module_key, is_enabled=True)
    return tenant


def _add_member(tenant, username, role=None, tg_chat_id=None):
    user = User.objects.create_user(
        username=username,
        password="x",
        telegram_chat_id=tg_chat_id,
        telegram_from_id=tg_chat_id,
    )
    TenantMembership.objects.create(tenant=tenant, user=user, is_active=True)
    if role:
        TenantUserRole.objects.create(tenant=tenant, user=user, role=role)
    return user


def _make_task(tenant, assignee, title="Test task", status=Task.STATUS_NEW):
    return Task.objects.create(
        tenant=tenant,
        assignee=assignee,
        title=title,
        status=status,
        source_type=Task.SOURCE_MANUAL,
    )


# ---------------------------------------------------------------------------
# REST API — task board and status transitions
# ---------------------------------------------------------------------------

@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TasksApiTests(APITestCase):
    def setUp(self):
        self.tenant = _setup_tenant()
        self.admin = _add_member(self.tenant, "admin_user", role=TenantUserRole.ROLE_ADMIN)
        self.regular = _add_member(self.tenant, "regular_user", role=TenantUserRole.ROLE_REQUESTER)
        self.other = _add_member(self.tenant, "other_user", role=TenantUserRole.ROLE_REQUESTER)

    def _auth(self, user):
        self.client.force_authenticate(user)
        self.client.defaults["HTTP_HOST"] = HOST

    # ------------------------------------------------------------------
    # Scoping
    # ------------------------------------------------------------------

    def test_regular_user_sees_only_own_tasks(self):
        _make_task(self.tenant, self.regular, "My task")
        _make_task(self.tenant, self.other, "Other task")

        self._auth(self.regular)
        res = self.client.get("/api/tasks/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        titles = [t["title"] for t in res.data]
        self.assertIn("My task", titles)
        self.assertNotIn("Other task", titles)

    def test_admin_sees_all_tenant_tasks(self):
        _make_task(self.tenant, self.regular, "Regular task")
        _make_task(self.tenant, self.other, "Other task")

        self._auth(self.admin)
        res = self.client.get("/api/tasks/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        titles = [t["title"] for t in res.data]
        self.assertIn("Regular task", titles)
        self.assertIn("Other task", titles)

    def test_regular_user_cannot_access_other_users_task(self):
        task = _make_task(self.tenant, self.other, "Private task")
        self._auth(self.regular)
        res = self.client.get(f"/api/tasks/{task.id}/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 404)

    # ------------------------------------------------------------------
    # Status filter
    # ------------------------------------------------------------------

    def test_status_filter_returns_only_matching(self):
        _make_task(self.tenant, self.regular, "New task", Task.STATUS_NEW)
        _make_task(self.tenant, self.regular, "Done task", Task.STATUS_DONE)

        self._auth(self.regular)
        res = self.client.get("/api/tasks/?status=new", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(all(t["status"] == "new" for t in res.data))

    # ------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------

    def test_change_status_new_to_in_progress(self):
        task = _make_task(self.tenant, self.regular, "Work task")
        self._auth(self.regular)
        res = self.client.post(
            f"/api/tasks/{task.id}/status/",
            {"status": "in_progress"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["status"], "in_progress")

    def test_change_status_to_done_sets_completed_at(self):
        task = _make_task(self.tenant, self.regular, "Finish task")
        self._auth(self.regular)
        res = self.client.post(
            f"/api/tasks/{task.id}/status/",
            {"status": "done"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.data["completed_at"])

    def test_done_task_cannot_transition(self):
        task = _make_task(self.tenant, self.regular, "Done task", Task.STATUS_DONE)
        self._auth(self.regular)
        res = self.client.post(
            f"/api/tasks/{task.id}/status/",
            {"status": "in_progress"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 400)

    def test_other_user_cannot_change_status_of_others_task(self):
        task = _make_task(self.tenant, self.other, "Other task")
        self._auth(self.regular)
        res = self.client.post(
            f"/api/tasks/{task.id}/status/",
            {"status": "in_progress"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertIn(res.status_code, [403, 404])

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def test_assignee_can_add_comment(self):
        task = _make_task(self.tenant, self.regular, "Commented task")
        self._auth(self.regular)
        res = self.client.post(
            f"/api/tasks/{task.id}/comments/",
            {"body": "Hello"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["body"], "Hello")

    def test_admin_comment_is_marked_as_admin_comment(self):
        task = _make_task(self.tenant, self.regular, "Task for admin comment")
        self._auth(self.admin)
        res = self.client.post(
            f"/api/tasks/{task.id}/comments/",
            {"body": "Director note"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data["is_admin_comment"])

    # ------------------------------------------------------------------
    # Manual create
    # ------------------------------------------------------------------

    def test_create_manual_task(self):
        self._auth(self.admin)
        res = self.client.post(
            "/api/tasks/",
            {"title": "Manual task", "assignee_id": self.regular.id},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["title"], "Manual task")
        self.assertEqual(res.data["status"], "new")

    # ------------------------------------------------------------------
    # Assignee candidates
    # ------------------------------------------------------------------

    def test_assignee_candidates_returns_active_members(self):
        self._auth(self.regular)
        res = self.client.get("/api/tasks/assignee-candidates/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        usernames = [c["username"] for c in res.data]
        self.assertIn("admin_user", usernames)
        self.assertIn("regular_user", usernames)
        self.assertIn("other_user", usernames)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def test_dashboard_returns_three_columns(self):
        _make_task(self.tenant, self.regular, "New", Task.STATUS_NEW)
        _make_task(self.tenant, self.regular, "WIP", Task.STATUS_IN_PROGRESS)
        _make_task(self.tenant, self.regular, "Done", Task.STATUS_DONE)

        self._auth(self.regular)
        res = self.client.get("/api/tasks/dashboard/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        self.assertIn("new", res.data)
        self.assertIn("in_progress", res.data)
        self.assertIn("done_recent", res.data)
        self.assertEqual(len(res.data["new"]), 1)
        self.assertEqual(len(res.data["in_progress"]), 1)
        self.assertEqual(len(res.data["done_recent"]), 1)

    def test_dashboard_done_capped_at_3(self):
        for i in range(5):
            _make_task(self.tenant, self.regular, f"Done {i}", Task.STATUS_DONE)

        self._auth(self.regular)
        res = self.client.get("/api/tasks/dashboard/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(len(res.data["done_recent"]), 3)
