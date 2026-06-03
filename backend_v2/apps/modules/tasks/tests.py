from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from unittest.mock import patch

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


def _make_task(tenant, assignee, title="Test task", status=Task.Status.NEW, created_by=None):
    creator = created_by or assignee
    return Task.objects.create(
        tenant=tenant,
        assignee=assignee,
        created_by=creator,
        title=title,
        status=status,
        last_edit_at=timezone.now(),
        last_edit_by=creator,
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

    def test_regular_user_gets_403_on_other_users_task(self):
        task = _make_task(self.tenant, self.other, "Private task")
        self._auth(self.regular)
        res = self.client.get(f"/api/tasks/{task.id}/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 403)

    # ------------------------------------------------------------------
    # Status filter
    # ------------------------------------------------------------------

    def test_status_filter_returns_only_matching(self):
        _make_task(self.tenant, self.regular, "New task", Task.Status.NEW)
        _make_task(self.tenant, self.regular, "Done task", Task.Status.DONE)

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
        task = _make_task(self.tenant, self.regular, "Done task", Task.Status.DONE)
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

    def test_assignee_candidates_admin_sees_all_active_members(self):
        self._auth(self.admin)
        res = self.client.get("/api/tasks/assignee-candidates/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        usernames = [c["username"] for c in res.data]
        self.assertIn("admin_user", usernames)
        self.assertIn("regular_user", usernames)
        self.assertIn("other_user", usernames)

    def test_assignee_candidates_regular_user_sees_only_self(self):
        # Non-admin/director users can only assign tasks to themselves, so the
        # candidate list must be limited to the requesting user — exposing other
        # members would suggest a capability they do not have.
        self._auth(self.regular)
        res = self.client.get("/api/tasks/assignee-candidates/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        usernames = [c["username"] for c in res.data]
        self.assertEqual(usernames, ["regular_user"])

    def test_create_task_regular_user_cannot_assign_to_others(self):
        self._auth(self.regular)
        res = self.client.post(
            "/api/tasks/",
            {"title": "Task for other", "assignee_id": self.other.id},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("assignee_id", res.data)

    def test_create_task_regular_user_can_self_assign(self):
        self._auth(self.regular)
        res = self.client.post(
            "/api/tasks/",
            {"title": "My own task", "assignee_id": self.regular.id},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data["assignee"]["id"], self.regular.id)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    def test_dashboard_returns_three_columns(self):
        _make_task(self.tenant, self.regular, "New", Task.Status.NEW)
        _make_task(self.tenant, self.regular, "WIP", Task.Status.IN_PROGRESS)
        _make_task(self.tenant, self.regular, "Done", Task.Status.DONE)

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
            _make_task(self.tenant, self.regular, f"Done {i}", Task.Status.DONE)

        self._auth(self.regular)
        res = self.client.get("/api/tasks/dashboard/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 200)
        self.assertLessEqual(len(res.data["done_recent"]), 3)

    # ------------------------------------------------------------------
    # Delete (CanDeleteTask)
    # ------------------------------------------------------------------

    def _make_task_with_creator(self, *, assignee, created_by, title="Test"):
        return Task.objects.create(
            tenant=self.tenant,
            assignee=assignee,
            created_by=created_by,
            title=title,
            status=Task.Status.NEW,
            last_edit_at=timezone.now(),
            last_edit_by=created_by,
        )

    def test_creator_can_delete_own_task(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.regular)
        self._auth(self.regular)
        res = self.client.delete(f"/api/tasks/{task.id}/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Task.objects.filter(pk=task.id).exists())

    def test_admin_can_delete_any_task(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.regular)
        self._auth(self.admin)
        res = self.client.delete(f"/api/tasks/{task.id}/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 204)

    def test_non_creator_non_admin_cannot_delete(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.admin)
        self._auth(self.regular)
        res = self.client.delete(f"/api/tasks/{task.id}/", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 403)
        self.assertTrue(Task.objects.filter(pk=task.id).exists())

    # ------------------------------------------------------------------
    # Edit (CanEditTask)
    # ------------------------------------------------------------------

    def test_creator_can_patch_own_task(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.regular)
        self._auth(self.regular)
        res = self.client.patch(
            f"/api/tasks/{task.id}/",
            {"title": "Updated title", "description": "New body"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["title"], "Updated title")
        self.assertEqual(res.data["description"], "New body")

    def test_admin_can_patch_any_task(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.regular)
        self._auth(self.admin)
        res = self.client.patch(
            f"/api/tasks/{task.id}/",
            {"title": "Admin edit"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["title"], "Admin edit")

    def test_non_creator_non_admin_cannot_patch(self):
        # Assignee who didn't create the task cannot edit title/description —
        # editing is a creator/admin power, not an assignee power.
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.admin)
        self._auth(self.regular)
        res = self.client.patch(
            f"/api/tasks/{task.id}/",
            {"title": "Hacked title"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 403)
        task.refresh_from_db()
        self.assertNotEqual(task.title, "Hacked title")

    # ------------------------------------------------------------------
    # Remind (CanRemindTask)
    # ------------------------------------------------------------------

    def test_admin_can_call_remind(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.admin)
        self._auth(self.admin)
        res = self.client.post(f"/api/tasks/{task.id}/remind/", {}, format="json", HTTP_HOST=HOST)
        # The endpoint logs+swallows Telegram errors; what we verify is that
        # the permission layer accepts the call (200), not that a message was sent.
        self.assertEqual(res.status_code, 200)

    def test_regular_user_cannot_call_remind(self):
        task = self._make_task_with_creator(assignee=self.regular, created_by=self.admin)
        self._auth(self.regular)
        res = self.client.post(f"/api/tasks/{task.id}/remind/", {}, format="json", HTTP_HOST=HOST)
        self.assertEqual(res.status_code, 403)

    # ------------------------------------------------------------------
    # URL validation for config endpoint
    # ------------------------------------------------------------------

    def test_config_patch_rejects_invalid_url(self):
        self._auth(self.admin)
        res = self.client.patch(
            "/api/tasks/config/",
            {"tasks_webapp_url": "not-a-url"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("tasks_webapp_url", res.data)

    def test_config_patch_accepts_valid_url(self):
        self._auth(self.admin)
        res = self.client.patch(
            "/api/tasks/config/",
            {"tasks_webapp_url": "https://t.me/mybot/tasks"},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["tasks_webapp_url"], "https://t.me/mybot/tasks")

    def test_config_patch_accepts_empty_url(self):
        self._auth(self.admin)
        res = self.client.patch(
            "/api/tasks/config/",
            {"tasks_webapp_url": ""},
            format="json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(res.status_code, 200)


@override_settings(BASE_DOMAIN="example.com", ALLOWED_HOSTS=["*"])
class TaskNotifierTransportTests(APITestCase):
    def setUp(self):
        self.tenant = _setup_tenant()
        self.admin = _add_member(self.tenant, "task_admin", role=TenantUserRole.ROLE_ADMIN, tg_chat_id=10101)
        self.task = _make_task(self.tenant, self.admin, "Transport task", Task.Status.NEW, created_by=self.admin)

    @patch("apps.modules.telegram_approvals.services.post_messaging_gateway")
    def test_task_notifier_uses_gateway_value_buttons(self, mocked_gateway):
        from apps.modules.tasks.notifications.task_notifier import send_task_notification

        mocked_gateway.return_value = {"message_id": 777}
        send_task_notification(task=self.task, tenant=self.tenant, bot_token="token")

        self.assertTrue(mocked_gateway.called)
        payload = mocked_gateway.call_args.kwargs["payload"]
        first_button = payload["buttons"][0][0]
        self.assertIn("value", first_button)
        self.assertNotIn("callback_data", first_button)

