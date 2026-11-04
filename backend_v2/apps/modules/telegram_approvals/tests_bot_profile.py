from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.modules.telegram_approvals import bot_profile
from apps.modules.telegram_approvals.command_handlers import WALLET_BALANCE_COMMANDS
from apps.tenants.models import Tenant

POST = "apps.modules.telegram_approvals.bot_profile.requests.post"
GATEWAY = "http://tg_gateway:8080"


def _resp(ok=True, status=200, description=None):
    r = MagicMock()
    r.status_code = status
    body = {"ok": ok, "telegram": {"ok": ok}}
    if description:
        body["telegram"]["description"] = description
    r.content = b"{}"
    r.json.return_value = body
    return r


def _make_tenant(subdomain="acme-bp", token="123456:abcdef", **kwargs):
    tenant = Tenant.objects.create(name=subdomain, subdomain=subdomain, is_active=True, **kwargs)
    if token:
        tenant.set_telegram_bot_token(token)
        tenant.save(update_fields=["telegram_bot_token_enc"])
    return tenant


@override_settings(BASE_DOMAIN="kolberg.uz")
class SyncBotProfileTests(TestCase):
    @patch(POST)
    def test_sync_sends_commands_description_and_menu_button(self, mocked_post):
        mocked_post.return_value = _resp()
        tenant = _make_tenant()

        result = bot_profile.sync_bot_profile(tenant)

        self.assertEqual(
            result,
            bot_profile.BotProfileSyncResult(
                tenant_id=tenant.pk, commands_ok=True, description_ok=True, menu_button_ok=True
            ),
        )
        calls = mocked_post.call_args_list
        self.assertEqual(
            [c.args[0] for c in calls],
            [
                f"{GATEWAY}/v1/messaging/commands/set",
                f"{GATEWAY}/v1/messaging/description/set",
                f"{GATEWAY}/v1/messaging/menu-button/set",
            ],
        )
        self.assertEqual(
            calls[0].kwargs["json"],
            {
                "bot_token": "123456:abcdef",
                "commands": [
                    {"command": s.command, "description": s.title} for s in WALLET_BALANCE_COMMANDS.values()
                ],
            },
        )
        self.assertEqual(
            calls[1].kwargs["json"],
            {
                "bot_token": "123456:abcdef",
                "description": bot_profile.BASE_DESCRIPTION,
                "short_description": bot_profile.SHORT_DESCRIPTION,
            },
        )
        self.assertEqual(
            calls[2].kwargs["json"],
            {"bot_token": "123456:abcdef", "text": "Портал", "url": "https://acme-bp.kolberg.uz/app/tg/"},
        )

    @patch("apps.modules.ai_assistant.access.assistant_enabled", return_value=True)
    @patch(POST)
    def test_assistant_enabled_description_mentions_questions(self, mocked_post, _enabled):
        mocked_post.return_value = _resp()
        tenant = _make_tenant()

        bot_profile.sync_bot_profile(tenant)

        payload = mocked_post.call_args_list[1].kwargs["json"]
        self.assertIn("написать вопрос", payload["description"])
        self.assertTrue(payload["description"].startswith(bot_profile.BASE_DESCRIPTION))
        self.assertEqual(payload["short_description"], bot_profile.ASSISTANT_SHORT_DESCRIPTION)
        self.assertLessEqual(len(payload["description"]), 512)
        self.assertLessEqual(len(payload["short_description"]), 120)

    @patch(POST)
    def test_one_failed_call_does_not_stop_others(self, mocked_post):
        mocked_post.side_effect = [_resp(ok=False, status=502, description="boom"), _resp(), _resp()]
        tenant = _make_tenant()

        with self.assertLogs(bot_profile.logger, level="WARNING") as logs:
            result = bot_profile.sync_bot_profile(tenant)

        self.assertEqual(mocked_post.call_count, 3)
        self.assertFalse(result.commands_ok)
        self.assertTrue(result.description_ok)
        self.assertTrue(result.menu_button_ok)
        joined = "\n".join(logs.output)
        self.assertIn("boom", joined)
        self.assertNotIn("123456:abcdef", joined)

    @patch(POST)
    def test_unexpected_error_in_one_part_does_not_raise(self, mocked_post):
        bad = MagicMock()
        bad.status_code = 200
        bad.content = b"[]"
        bad.json.return_value = ["not", "a", "dict"]
        mocked_post.side_effect = [bad, _resp(), _resp()]
        tenant = _make_tenant()

        with self.assertLogs(bot_profile.logger, level="WARNING"):
            with patch.object(bot_profile, "_assistant_enabled", side_effect=RuntimeError("x")):
                result = bot_profile.sync_bot_profile(tenant)

        self.assertFalse(result.commands_ok)
        self.assertFalse(result.description_ok)
        self.assertTrue(result.menu_button_ok)

    @patch(POST)
    def test_no_token_returns_none(self, mocked_post):
        tenant = _make_tenant(subdomain="nobot-bp", token="")

        self.assertIsNone(bot_profile.sync_bot_profile(tenant))
        mocked_post.assert_not_called()

    @override_settings(BASE_DOMAIN="")
    @patch(POST)
    def test_empty_base_domain_skips_menu_button(self, mocked_post):
        mocked_post.return_value = _resp()
        tenant = _make_tenant()

        with self.assertLogs(bot_profile.logger, level="WARNING"):
            result = bot_profile.sync_bot_profile(tenant)

        self.assertIsNone(result.menu_button_ok)
        self.assertEqual(mocked_post.call_count, 2)
        urls = [c.args[0] for c in mocked_post.call_args_list]
        self.assertNotIn(f"{GATEWAY}/v1/messaging/menu-button/set", urls)


@override_settings(BASE_DOMAIN="kolberg.uz")
class SyncTelegramBotsCommandTests(TestCase):
    @patch(POST)
    def test_command_prints_summary_and_exits_zero(self, mocked_post):
        good = _make_tenant(subdomain="good-bp", token="111:aaa")
        bad = _make_tenant(subdomain="bad-bp", token="222:bbb")
        _make_tenant(subdomain="none-bp", token="")

        def fake_post(url, json=None, timeout=None):
            if json["bot_token"] == "222:bbb" and url.endswith("/description/set"):
                return _resp(ok=False, status=502, description="nope")
            return _resp()

        mocked_post.side_effect = fake_post
        out = StringIO()

        call_command("sync_telegram_bots", stdout=out)  # must not raise

        text = out.getvalue()
        self.assertIn("sync_telegram_bots: 1 bots fully synced, 1 with errors, 1 without token", text)
        self.assertIn("bad-bp: description", text)
        self.assertNotIn("good-bp:", text)
        self.assertNotIn("222:bbb", text)
        self.assertTrue(good.pk and bad.pk)
