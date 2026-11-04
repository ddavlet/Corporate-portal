from unittest import mock

from django.test import SimpleTestCase

from apps.modules.ai_assistant import telegram_out
from apps.modules.ai_assistant.telegram_out import (
    render_confirmation,
    send_answer,
    send_confirmation,
    split_message,
    to_telegram_html,
)
from apps.modules.telegram_approvals.services import build_gateway_payload


def _payload(**extra):
    return build_gateway_payload(
        action="send",
        tenant_id=1,
        recipient_id=5,
        bot_token="t",
        message_text="x",
        **extra,
    )


class GatewayPayloadTests(SimpleTestCase):
    def test_build_gateway_payload_reply_to_only_when_given(self):
        self.assertNotIn("reply_to_message_id", _payload())
        self.assertEqual(_payload(reply_to_message_id=77)["reply_to_message_id"], 77)


class SanitizerTests(SimpleTestCase):
    def test_to_telegram_html_escapes_lt_amp_and_unknown_tags(self):
        out = to_telegram_html("сумма < 100 & <script>x</script> <b>ок</b>")
        self.assertEqual(out, "сумма &lt; 100 &amp; &lt;script&gt;x&lt;/script&gt; <b>ок</b>")

    def test_unbalanced_tags_are_closed_and_case_normalized(self):
        self.assertEqual(to_telegram_html("<B>a<i>b</B>"), "<b>a<i>b</i></b>")
        self.assertEqual(to_telegram_html("<b>open"), "<b>open</b>")

    def test_link_keeps_only_safe_href(self):
        self.assertEqual(
            to_telegram_html('<a href="https://x.y/?a=1&b=2" onclick="z">m</a>'),
            '<a href="https://x.y/?a=1&amp;b=2">m</a>',
        )
        self.assertEqual(to_telegram_html('<a href="javascript:alert(1)">l</a>'), "l")

    def test_entities_preserved_and_bare_amp_escaped(self):
        self.assertEqual(to_telegram_html("a &amp; b &#65; AT&T"), "a &amp; b &#65; AT&amp;T")


class SplitTests(SimpleTestCase):
    def test_split_message_respects_limit_and_tags(self):
        text = to_telegram_html(("Абзац текста. " * 40 + "\n\n") * 20)
        self.assertGreater(len(text), 9000)
        parts = split_message(text)
        self.assertGreaterEqual(len(parts), 3)
        for part in parts:
            self.assertLessEqual(len(part), 4096)
            self.assertEqual(to_telegram_html(part), part)

    def test_split_inside_pre_closes_and_reopens(self):
        text = to_telegram_html("<pre>" + "line of code\n" * 600 + "</pre>")
        parts = split_message(text)
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertLessEqual(len(part), 4096)
            self.assertTrue(part.startswith("<pre>"))
            self.assertTrue(part.endswith("</pre>"))

    def test_hard_split_without_separators(self):
        parts = split_message("x" * 9000)
        self.assertEqual([len(p) for p in parts], [4096, 4096, 808])


class ConfirmationTests(SimpleTestCase):
    def test_render_confirmation_shows_actual_arguments(self):
        text = render_confirmation(
            [{"name": "create_expense", "input": {"amount": 100, "note": "<x> & y", "tags": ["a"]}}],
            {"create_expense": "Создать расход.\nВторая строка."},
        )
        self.assertTrue(text.startswith("Подтвердите действие:"))
        self.assertIn("Создать расход.", text)
        self.assertNotIn("Вторая строка", text)
        self.assertIn("amount: <code>100</code>", text)
        self.assertIn("&lt;x&gt; &amp; y", text)
        self.assertIn('<code>["a"]</code>', text.replace("&quot;", '"'))

    def test_render_confirmation_skips_calculator_calls(self):
        text = render_confirmation(
            [
                {"id": "tu_c", "name": "calculate", "input": {"expression": "1 + 1"}},
                {"id": "tu_w", "name": "create_expense", "input": {"amount": 100}},
            ],
            {"create_expense": "Создать расход."},
        )
        self.assertNotIn("calculate", text)
        self.assertNotIn("1 + 1", text)
        self.assertIn("create_expense", text)

    def test_confirmation_buttons_values(self):
        with mock.patch.object(telegram_out, "TelegramDispatcher") as dispatcher:
            send_confirmation(mock.Mock(), "5", 9, 42, "t")
        kwargs = dispatcher.return_value.send.call_args.kwargs
        self.assertEqual(kwargs["action"], "send_interactive")
        self.assertEqual(kwargs["reply_to_message_id"], 9)
        self.assertEqual(
            kwargs["buttons"],
            [[
                {"label": "✅ Подтвердить", "value": "aiq:42:y"},
                {"label": "❌ Отменить", "value": "aiq:42:n"},
            ]],
        )


class SendAnswerTests(SimpleTestCase):
    def test_parts_reply_to_previous_part(self):
        sent = [mock.Mock(message_id=101), mock.Mock(message_id=102), mock.Mock(message_id=103)]
        with mock.patch.object(telegram_out, "TelegramDispatcher") as dispatcher:
            dispatcher.return_value.send.side_effect = sent
            result = send_answer(mock.Mock(), "5", 100, "x" * 9000)
        self.assertEqual(result, sent)
        replies = [c.kwargs["reply_to_message_id"] for c in dispatcher.return_value.send.call_args_list]
        self.assertEqual(replies, [100, 101, 102])

    def test_failure_stops_and_returns_sent(self):
        first = mock.Mock(message_id=101)
        with mock.patch.object(telegram_out, "TelegramDispatcher") as dispatcher:
            dispatcher.return_value.send.side_effect = [first, RuntimeError("boom")]
            result = send_answer(mock.Mock(), "5", 100, "x" * 9000)
        self.assertEqual(result, [first])

    def test_none_result_stops_sending(self):
        first = mock.Mock(message_id=101)
        with mock.patch.object(telegram_out, "TelegramDispatcher") as dispatcher:
            dispatcher.return_value.send.side_effect = [first, None, mock.Mock(message_id=103)]
            result = send_answer(mock.Mock(), "5", 100, "x" * 9000)
        self.assertEqual(result, [first])
        self.assertEqual(dispatcher.return_value.send.call_count, 2)
