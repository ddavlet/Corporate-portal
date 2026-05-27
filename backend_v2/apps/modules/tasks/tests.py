from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.modules.tasks.models import Task, TaskComment, TasksConfig
from apps.modules.tasks.notifications.digest_formatter import digest_buttons, format_digest
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
# Digest formatter
# ---------------------------------------------------------------------------

class DigestFormatterTests(APITestCase):
    def setUp(self):
        self.tenant = _setup_tenant()
        self.user = _add_member(self.tenant, "alice", role=TenantUserRole.ROLE_REQUESTER)

    def _task(self, title, status=Task.STATUS_NEW, source_request_id=None):
        t = Task(
            tenant=self.tenant,
            assignee=self.user,
            title=title,
            status=status,
            source_type=Task.SOURCE_MANUAL,
        )
        t.source_request_id = source_request_id
        return t

    def test_format_digest_includes_all_sections(self):
        dashboard = {
            "new": [self._task("Approve request #1", source_request_id=1)],
            "in_progress": [self._task("Process payment", Task.STATUS_IN_PROGRESS)],
            "done_recent": [self._task("Old task", Task.STATUS_DONE)],
        }
        text = format_digest(user=self.user, dashboard=dashboard)
        self.assertIn("alice", text)
        self.assertIn("НОВЫЕ", text)
        self.assertIn("В РАБОТЕ", text)
        self.assertIn("ВЫПОЛНЕНО", text)
        self.assertIn("заявка #1", text)

    def test_format_digest_empty_dashboard_no_active_tasks_message(self):
        dashboard = {"new": [], "in_progress": [], "done_recent": []}
        text = format_digest(user=self.user, dashboard=dashboard)
        self.assertIn("нет активных задач", text.lower())
        self.assertNotIn("НОВЫЕ", text)
        self.assertNotIn("В РАБОТЕ", text)

    def test_format_digest_only_new_tasks(self):
        dashboard = {
            "new": [self._task("Buy milk"), self._task("Send report")],
            "in_progress": [],
            "done_recent": [],
        }
        text = format_digest(user=self.user, dashboard=dashboard)
        self.assertIn("НОВЫЕ (2)", text)
        self.assertNotIn("В РАБОТЕ", text)
        self.assertNotIn("ВЫПОЛНЕНО", text)

    def test_digest_buttons_with_url_returns_row(self):
        buttons = digest_buttons(tasks_webapp_url="https://t.me/mybot/tasks")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0][0]["url"], "https://t.me/mybot/tasks")
        self.assertIn("задачи", buttons[0][0]["label"].lower())

    def test_digest_buttons_empty_url_returns_empty(self):
        self.assertEqual(digest_buttons(tasks_webapp_url=""), [])
        self.assertEqual(digest_buttons(tasks_webapp_url="   "), [])


# ---------------------------------------------------------------------------
# send_task_digest management command
# ---------------------------------------------------------------------------

@override_settings(
    MESSAGING_GATEWAY_SEND_URL="https://gw.example.com/send",
    BASE_DOMAIN="example.com",
)
class SendTaskDigestCommandTests(APITestCase):
    def setUp(self):
        self.tenant = _setup_tenant(subdomain="beta")
        self.tenant.set_telegram_bot_token("111:TESTTOKEN")
        self.tenant.save(update_fields=["telegram_bot_token_enc"])

        self.user = _add_member(
            self.tenant, "bob", role=TenantUserRole.ROLE_REQUESTER, tg_chat_id=123456
        )
        _make_task(self.tenant, self.user, "Task A")

    def _run(self):
        out = StringIO()
        call_command("send_task_digest", stdout=out)
        return out.getvalue()

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_sends_message_for_user_with_tg_chat_id(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {}

        output = self._run()

        self.assertTrue(mock_post.called)
        payload = mock_post.call_args.kwargs.get("json", {})
        self.assertEqual(payload["recipient_id"], "123456")
        self.assertEqual(payload["bot_token"], "111:TESTTOKEN")
        self.assertIn("text", payload)
        self.assertIn("bob", payload["text"])
        self.assertIn("sent=1", output)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_skips_user_without_telegram_chat_id(self, mock_post):
        user_no_tg = _add_member(self.tenant, "carol", role=TenantUserRole.ROLE_REQUESTER)
        _make_task(self.tenant, user_no_tg, "Carol task")

        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {}

        output = self._run()
        self.assertIn("skipped_no_tg=1", output)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_skips_tenant_without_bot_token(self, mock_post):
        tenant2 = _setup_tenant(subdomain="gamma")
        user2 = _add_member(tenant2, "dave", role=TenantUserRole.ROLE_REQUESTER, tg_chat_id=999)
        _make_task(tenant2, user2, "Dave task")

        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {}

        output = self._run()
        self.assertIn("skipped_no_token=1", output)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_skips_user_with_no_tasks(self, mock_post):
        user_idle = _add_member(
            self.tenant, "eve", role=TenantUserRole.ROLE_REQUESTER, tg_chat_id=777777
        )
        # no tasks for eve

        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {}

        output = self._run()
        self.assertIn("skipped_empty=1", output)

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_webapp_url_included_in_buttons_when_configured(self, mock_post):
        TasksConfig.objects.create(
            tenant=self.tenant, tasks_webapp_url="https://t.me/mybot/tasks"
        )
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {}

        self._run()

        payload = mock_post.call_args.kwargs.get("json", {})
        buttons = payload.get("buttons", [])
        self.assertTrue(len(buttons) > 0)
        self.assertEqual(buttons[0][0]["url"], "https://t.me/mybot/tasks")

    @patch("apps.modules.telegram_approvals.services.requests.post")
    def test_no_buttons_when_webapp_url_not_configured(self, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.content = b"{}"
        mock_post.return_value.json.return_value = {}

        self._run()

        payload = mock_post.call_args.kwargs.get("json", {})
        self.assertEqual(payload.get("buttons"), [])


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
