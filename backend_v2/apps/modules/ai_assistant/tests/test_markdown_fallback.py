from unittest import mock

from django.test import SimpleTestCase

from apps.modules.ai_assistant import telegram_out
from apps.modules.ai_assistant.markdown_fallback import markdown_to_telegram_html
from apps.modules.ai_assistant.prompts import SYSTEM_PROMPT
from apps.modules.ai_assistant.telegram_out import render_answer_html, send_answer


class MarkdownFallbackTests(SimpleTestCase):
    def test_bold_and_dash_list_from_real_answer(self):
        text = "Да.\n\n- **Вложение №189:** 21 005 000 UZS\n- **Касса:** приход"
        self.assertEqual(
            markdown_to_telegram_html(text),
            "Да.\n\n• <b>Вложение №189:</b> 21 005 000 UZS\n• <b>Касса:</b> приход",
        )

    def test_heading_inline_code_and_fence(self):
        self.assertEqual(markdown_to_telegram_html("## Итого"), "<b>Итого</b>")
        self.assertEqual(markdown_to_telegram_html("код `a**b**`"), "код <code>a**b**</code>")
        self.assertEqual(markdown_to_telegram_html("```\n**raw**\n```"), "<pre>**raw**</pre>")

    def test_existing_html_and_code_blocks_untouched(self):
        self.assertEqual(markdown_to_telegram_html("<b>уже</b> **ок**"), "<b>уже</b> <b>ок</b>")
        self.assertEqual(markdown_to_telegram_html("<code>**x**</code>"), "<code>**x**</code>")
        self.assertEqual(markdown_to_telegram_html("<pre>- **x**</pre>"), "<pre>- **x**</pre>")

    def test_arithmetic_and_identifiers_not_changed(self):
        text = "2 * 3 * 4, a ** b, snake__case__name, -5 UZS"
        self.assertEqual(markdown_to_telegram_html(text), text)

    def test_render_answer_html_sanitizes_after_conversion(self):
        self.assertEqual(render_answer_html("**a < b**"), "<b>a &lt; b</b>")

    def test_send_answer_sends_converted_html(self):
        with mock.patch.object(telegram_out, "TelegramDispatcher") as dispatcher:
            dispatcher.return_value.send.return_value = mock.Mock(message_id=101)
            send_answer(mock.Mock(), "5", 100, "- **Касса:** приход")
        self.assertEqual(dispatcher.return_value.send.call_args.kwargs["text"], "• <b>Касса:</b> приход")


class PromptFormatAndTimezoneTests(SimpleTestCase):
    def test_prompt_forbids_markdown_and_sets_tashkent_time(self):
        self.assertIn("Never write **", SYSTEM_PROMPT)
        self.assertIn("Asia/Tashkent", SYSTEM_PROMPT)
        self.assertIn("do not label times as UTC", SYSTEM_PROMPT)
        self.assertTrue(SYSTEM_PROMPT.isascii())
