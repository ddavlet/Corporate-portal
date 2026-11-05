import asyncio
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.modules.ai_assistant import addressee
from apps.modules.ai_assistant.addressee import (
    ADDRESSEE_PROMPT,
    AddresseeVerdict,
    classify_addressee,
    render_addressee_input,
)
from apps.modules.ai_assistant.config import ADDRESSEE_MODEL
from apps.modules.ai_assistant.models import ChainNode


def _node(kind, text, label=""):
    return SimpleNamespace(kind=kind, text=text, author_label=label)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=321, output_tokens=12),
    )


class RenderInputTests(SimpleTestCase):
    def test_chain_authors_and_mention_flag(self):
        path = [
            _node(ChainNode.KIND_BOT_AUTO, "Касса — остатки"),
            _node(ChainNode.KIND_BOT_AGENT, "Остатки верные"),
            _node(ChainNode.KIND_MEMBER, "Все верно? @natali_reyna1", 'Dilshod "D"'),
        ]
        text = render_addressee_input(path, mentions_bot=False)
        self.assertIn('<message author="bot_notification">Касса — остатки</message>', text)
        self.assertIn('<message author="assistant_answer">Остатки верные</message>', text)
        self.assertIn(
            '<new_message author="Dilshod &quot;D&quot;" bot_mentioned="false">Все верно? @natali_reyna1</new_message>',
            text,
        )

    def test_text_is_escaped_clipped_and_history_limited(self):
        long = "x" * (addressee.ADDRESSEE_TEXT_LIMIT + 50)
        history = [_node(ChainNode.KIND_MEMBER, f"m{i}", "P") for i in range(10)]
        path = history + [_node(ChainNode.KIND_USER, "<b>a & b</b> " + long, "Boss")]
        text = render_addressee_input(path, mentions_bot=True)
        self.assertIn("&lt;b&gt;a &amp; b&lt;/b&gt;", text)
        self.assertIn('bot_mentioned="true"', text)
        self.assertNotIn(">m3<", text)
        self.assertIn(">m4<", text)
        self.assertIn("...</new_message>", text)


class ClassifyTests(SimpleTestCase):
    def _classify(self, response, mentions_bot=False):
        messages = FakeMessages(response)
        client = SimpleNamespace(messages=messages)
        path = [_node(ChainNode.KIND_BOT_AUTO, "Касса"), _node(ChainNode.KIND_MEMBER, "Все верно", "Наталья")]
        verdict = asyncio.run(classify_addressee(client, path, mentions_bot=mentions_bot))
        return verdict, messages.kwargs

    def test_parses_verdict_and_uses_strong_model_with_json_schema(self):
        verdict, kwargs = self._classify(_response('{"addressed": false, "reason": "confirmation to colleague"}'))
        self.assertEqual(
            verdict,
            AddresseeVerdict(addressed=False, reason="confirmation to colleague", input_tokens=321, output_tokens=12),
        )
        self.assertEqual(kwargs["model"], ADDRESSEE_MODEL)
        self.assertEqual(kwargs["model"], "claude-opus-5-5")
        # Opus 5.5: thinking отключить нельзя ({"type": "disabled"} даёт 400).
        self.assertNotIn("thinking", kwargs)
        self.assertEqual(kwargs["output_config"]["effort"], "medium")
        self.assertEqual(kwargs["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(kwargs["system"], ADDRESSEE_PROMPT)
        self.assertIn("<new_message", kwargs["messages"][0]["content"])

    def test_truncated_or_refused_answer_raises(self):
        for stop_reason in ("max_tokens", "refusal"):
            with self.subTest(stop_reason=stop_reason), self.assertRaises(ValueError):
                self._classify(_response('{"addressed": tr', stop_reason=stop_reason))

    def test_prompt_is_ascii_english_with_xml(self):
        ADDRESSEE_PROMPT.encode("ascii")
        for tag in ("<role>", "<task>", "<guidelines>", "<input_format>", "<output>"):
            self.assertIn(tag, ADDRESSEE_PROMPT)
