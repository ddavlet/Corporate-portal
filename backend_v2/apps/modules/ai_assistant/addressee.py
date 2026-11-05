"""Кому адресовано сообщение в группе: ассистенту или людям.

В группе бот получает упоминания и ответы на свои сообщения. Ответ на автоуведомление
или реплика с упоминанием коллеги («все верно? @natali») — это разговор людей, и бот
в нём молчит. Решает дешёвая модель по тексту, без жёстких правил.
"""

import json
import logging
from dataclasses import dataclass
from xml.sax.saxutils import escape

from .config import ADDRESSEE_CONTEXT_NODES, ADDRESSEE_MAX_TOKENS, ADDRESSEE_MODEL, ADDRESSEE_TEXT_LIMIT
from .models import ChainNode

logger = logging.getLogger(__name__)

_ATTR_ENTITIES = {'"': "&quot;", "'": "&apos;"}

ADDRESSEE_PROMPT = """<role>
You watch a Telegram group chat of a company. The chat has an AI assistant bot that answers questions about the company's finance portal (requests, cash, bank, payroll, tasks and so on). The same bot also posts automatic notifications, for example cash balances or approval requests. People in the chat talk to each other and sometimes to the assistant.
</role>

<task>
Decide whether the new message is addressed to the AI assistant and expects an answer from it.
</task>

<guidelines>
- A message is addressed to the assistant when the person asks it something, asks it to do something, or continues a conversation with one of its own answers.
- Replying to an automatic notification does not by itself mean talking to the assistant. People often reply to a notification to discuss it with colleagues or to confirm it, for example "all correct", "ok", "+", "paid", "agreed".
- When the message mentions a person by @username or by name and does not mention the assistant, it is addressed to that person, even if it is a reply to the bot.
- An explicit mention of the assistant usually means it is addressed to the assistant, unless the text clearly speaks about the bot to someone else.
- Short acknowledgements and thanks ("thanks", "got it", "ok") after an answer of the assistant need no answer: treat them as not addressed.
- Messages are mostly in Russian or Uzbek.
- If you are unsure, answer not addressed.
</guidelines>

<input_format>
The conversation is the chain of replies that leads to the new message, oldest first. Each message has an author: "assistant_answer" is an answer of the AI assistant, "bot_notification" is an automatic notification of the bot, any other author is a person. The new message carries bot_mentioned="true" when it mentions the assistant explicitly.
</input_format>

<output>
Return JSON with "addressed" (boolean) and "reason" (a few words in English).
</output>"""

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "addressed": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["addressed", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class AddresseeVerdict:
    addressed: bool
    reason: str
    input_tokens: int = 0
    output_tokens: int = 0


def _clip(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= ADDRESSEE_TEXT_LIMIT:
        return text
    return text[:ADDRESSEE_TEXT_LIMIT] + "..."


def _author(node: ChainNode) -> str:
    if node.kind == ChainNode.KIND_BOT_AGENT:
        return "assistant_answer"
    if node.kind == ChainNode.KIND_BOT_AUTO:
        return "bot_notification"
    return node.author_label or "person"


def render_addressee_input(path: list, *, mentions_bot: bool) -> str:
    """XML for the classifier: the reply chain (last nodes) and the new message (path[-1])."""
    *history, new = path
    history = history[-ADDRESSEE_CONTEXT_NODES:]
    lines = ["<conversation>"]
    for node in history:
        lines.append(
            f'<message author="{escape(_author(node), _ATTR_ENTITIES)}">{escape(_clip(node.text))}</message>'
        )
    lines.append("</conversation>")
    lines.append(
        f'<new_message author="{escape(_author(new), _ATTR_ENTITIES)}" '
        f'bot_mentioned="{"true" if mentions_bot else "false"}">{escape(_clip(new.text))}</new_message>'
    )
    return "\n".join(lines)


async def classify_addressee(client, path: list, *, mentions_bot: bool) -> AddresseeVerdict:
    """Ask the small model whether path[-1] is addressed to the assistant. Raises on API/format errors."""
    response = await client.messages.create(
        model=ADDRESSEE_MODEL,
        max_tokens=ADDRESSEE_MAX_TOKENS,
        system=ADDRESSEE_PROMPT,
        messages=[{"role": "user", "content": render_addressee_input(path, mentions_bot=mentions_bot)}],
        thinking={"type": "disabled"},
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
    )
    if response.stop_reason not in ("end_turn", "stop_sequence"):
        raise ValueError(f"addressee classifier stopped with {response.stop_reason}")
    text = next(block.text for block in response.content if block.type == "text")
    data = json.loads(text)
    usage = response.usage
    return AddresseeVerdict(
        addressed=bool(data["addressed"]),
        reason=str(data.get("reason") or ""),
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )
