"""Исходящая часть ассистента: санитайзер HTML, разбиение, typing, ответы, подтверждение."""

import html
import json
import logging
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from apps.modules.telegram_approvals.services import (
    TelegramDispatcher,
    build_gateway_payload,
    post_messaging_gateway,
)

from .calculator import CALCULATOR_TOOL_NAME
from .config import CALLBACK_PREFIX, TELEGRAM_TEXT_LIMIT
from .markdown_fallback import markdown_to_telegram_html

logger = logging.getLogger(__name__)

ALLOWED_TAGS = frozenset({"b", "strong", "i", "em", "u", "s", "code", "pre", "a", "blockquote"})
ALLOWED_URL_SCHEMES = frozenset({"http", "https", "tg"})
_SAFE_NAMED_ENTITIES = frozenset({"amp", "lt", "gt", "quot"})
_CHARREF_RE = re.compile(r"^(?:[0-9]{1,7}|[xX][0-9a-fA-F]{1,6})$")


# «&», после которого нет корректной сущности (&amp; &lt; &gt; &quot; &#123; &#x1F;).
_BARE_AMP_RE = re.compile(r"&(?!(?:amp|lt|gt|quot|#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6});)")


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        # Имя открытого тега; None — отброшенный <a> без валидной ссылки (только для парности).
        self.stack: list[str | None] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            self.out.append(html.escape(self.get_starttag_text() or f"<{tag}>", quote=False))
            return
        if tag == "a":
            href = next((v for k, v in attrs if k.lower() == "href" and v), None)
            scheme = urlparse(href.strip()).scheme.lower() if href else ""
            if href and scheme in ALLOWED_URL_SCHEMES:
                self.out.append(f'<a href="{html.escape(href.strip(), quote=True)}">')
                self.stack.append("a")
            else:
                self.stack.append(None)
            return
        self.out.append(f"<{tag}>")
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        # <br/> и подобные: разрешённые теги без содержимого не нужны, остальное экранируем.
        self.out.append(html.escape(self.get_starttag_text() or f"<{tag}/>", quote=False))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            self.out.append(html.escape(f"</{tag}>", quote=False))
            return
        key = "a" if tag == "a" else tag
        if key == "a":
            # </a> закрывает ближайший <a> — настоящий или отброшенный.
            idx = next(
                (i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i] in ("a", None)),
                None,
            )
        else:
            idx = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i] == key), None)
        if idx is None:
            return  # лишний закрывающий тег — отбрасываем
        while len(self.stack) > idx:
            name = self.stack.pop()
            if name:
                self.out.append(f"</{name}>")

    def handle_data(self, data):
        self.out.append(html.escape(data, quote=False))

    def handle_entityref(self, name):
        if name in _SAFE_NAMED_ENTITIES:
            self.out.append(f"&{name};")
        else:
            self.out.append(f"&amp;{html.escape(name, quote=False)};")

    def handle_charref(self, name):
        if _CHARREF_RE.match(name):
            self.out.append(f"&#{name};")
        else:
            self.out.append(f"&amp;#{html.escape(name, quote=False)};")

    def handle_comment(self, data):
        self.out.append(html.escape(f"<!--{data}-->", quote=False))

    def handle_decl(self, decl):
        self.out.append(html.escape(f"<!{decl}>", quote=False))

    def handle_pi(self, data):
        self.out.append(html.escape(f"<?{data}>", quote=False))

    def unknown_decl(self, data):
        self.out.append(html.escape(f"<![{data}]>", quote=False))

    def finish(self) -> str:
        self.close()
        while self.stack:
            name = self.stack.pop()
            if name:
                self.out.append(f"</{name}>")
        return "".join(self.out)


def to_telegram_html(text: str) -> str:
    """Оставляет только подмножество HTML, понятное Telegram; всё прочее экранирует."""
    if not text:
        return ""
    text = _BARE_AMP_RE.sub("&amp;", text)
    parser = _Sanitizer()
    parser.feed(text)
    return parser.finish()


_ATOM_RE = re.compile(r"<[^<>]*>|&[#A-Za-z0-9]+;|[\s\S]")
_TAG_NAME_RE = re.compile(r"^<\s*(/?)\s*([A-Za-z]+)")


def _tokenize(text: str) -> list[tuple[str, str, str]]:
    """Атомы: (kind, строка, имя тега). kind: open/close/other."""
    atoms = []
    for m in _ATOM_RE.finditer(text):
        s = m.group(0)
        if len(s) > 1 and s[0] == "<":
            tm = _TAG_NAME_RE.match(s)
            if tm:
                atoms.append(("close" if tm.group(1) else "open", s, tm.group(2).lower()))
                continue
        atoms.append(("other", s, ""))
    return atoms


def _closers(stack: list[tuple[str, str]]) -> str:
    return "".join(f"</{name}>" for name, _ in reversed(stack))


def _openers(stack: list[tuple[str, str]]) -> str:
    return "".join(open_str for _, open_str in stack)


def _apply(stack, kind, s, name):
    new = list(stack)
    if kind == "open":
        new.append((name, s))
    elif kind == "close":
        for i in range(len(new) - 1, -1, -1):
            if new[i][0] == name:
                del new[i:]
                break
    return new


def _has_visible_text(part: str) -> bool:
    return bool(re.sub(r"<[^<>]*>", "", part).strip())


def split_message(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Режет уже санитизированный HTML на части ≤ limit, каждая часть сама по себе well-formed."""
    if len(text) <= limit:
        return [text] if text else []
    atoms = _tokenize(text)
    n = len(atoms)
    parts: list[str] = []
    stack: list[tuple[str, str]] = []
    i = 0
    while i < n:
        # Пропускаем пустые строки в начале новой части.
        while i < n and atoms[i][1] == "\n" and parts:
            i += 1
        if i >= n:
            break
        prefix = _openers(stack)
        cur = [prefix]
        used = len(prefix)
        cur_stack = list(stack)
        start = i
        para_bp = line_bp = word_bp = None  # (индекс атома, длина cur, used, стек)
        j = i
        while j < n:
            kind, s, name = atoms[j]
            new_stack = _apply(cur_stack, kind, s, name)
            if used + len(s) + len(_closers(new_stack)) > limit:
                break
            cur.append(s)
            used += len(s)
            cur_stack = new_stack
            j += 1
            if s == "\n":
                snap = (j, len(cur), used, list(cur_stack))
                line_bp = snap
                if j - 2 >= start and atoms[j - 2][1] == "\n":
                    para_bp = snap
            elif s == " ":
                word_bp = (j, len(cur), used, list(cur_stack))
        if j >= n:
            parts.append("".join(cur) + _closers(cur_stack))
            break
        bp = para_bp or line_bp or word_bp
        if bp is None:
            if j == start:
                # Ничего не помещается (патологический случай) — отдаём один атом как есть.
                parts.append(atoms[j][1])
                i = j + 1
                continue
            bp = (j, len(cur), used, list(cur_stack))
        idx, cur_len, _, snap_stack = bp
        parts.append("".join(cur[:cur_len]) + _closers(snap_stack))
        stack = snap_stack
        i = idx
    return [p for p in parts if _has_visible_text(p)]


def send_typing(tenant, chat_id: str) -> None:
    """Индикатор «печатает…». Сбой логируется и не пробрасывается."""
    try:
        payload = build_gateway_payload(
            action="typing",
            tenant_id=getattr(tenant, "id", None),
            recipient_id=chat_id,
            bot_token=TelegramDispatcher(tenant).bot_token,
            message_text="",
        )
        post_messaging_gateway(tenant=tenant, payload=payload)
    except Exception:
        logger.exception("ai_assistant: failed to send typing chat_id=%s", chat_id)


def render_answer_html(text: str) -> str:
    """Ответ модели → безопасный Telegram HTML (случайный Markdown переводится в теги)."""
    return to_telegram_html(markdown_to_telegram_html(text))


def send_answer(tenant, chat_id: str, reply_to_message_id: int, text: str) -> list:
    """Санитизирует, режет и отправляет ответ; каждая часть отвечает на предыдущую."""
    parts = split_message(render_answer_html(text))
    dispatcher = TelegramDispatcher(tenant)
    sent = []
    reply_to = reply_to_message_id
    for part in parts:
        try:
            message = dispatcher.send(
                action="send",
                recipient_id=chat_id,
                text=part,
                reply_to_message_id=reply_to,
            )
        except Exception:
            logger.exception("ai_assistant: failed to send answer part chat_id=%s", chat_id)
            break
        if message is None:
            logger.warning("ai_assistant: gateway returned no message for answer part, stopping chat_id=%s", chat_id)
            break
        sent.append(message)
        reply_to = message.message_id
    return sent


def _format_value(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def render_confirmation(tool_calls: list[dict], tool_descriptions: dict[str, str]) -> str:
    """HTML-текст подтверждения: по каждому вызову — описание и все реальные аргументы."""
    esc = lambda v: html.escape(str(v), quote=False)  # noqa: E731
    blocks = ["Подтвердите действие:"]
    for call in tool_calls:
        name = call.get("name") or ""
        if name == CALCULATOR_TOOL_NAME:
            # Локальный read-only калькулятор: в pending он нужен для resume, пользователю не показывается.
            continue
        description = (tool_descriptions.get(name) or "").strip().splitlines()
        lines = [f"<b>{esc(name)}</b>"]
        if description:
            lines.append(esc(description[0].strip()))
        args = call.get("input") or {}
        if isinstance(args, dict):
            for key, value in args.items():
                lines.append(f"• {esc(key)}: <code>{esc(_format_value(value))}</code>")
        else:
            lines.append(f"• <code>{esc(_format_value(args))}</code>")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def send_confirmation(tenant, chat_id, reply_to_message_id, pending_id: int, text: str):
    """Сообщение с кнопками «Подтвердить»/«Отменить»."""
    buttons = [
        [
            {"label": "✅ Подтвердить", "value": f"{CALLBACK_PREFIX}{pending_id}:y"},
            {"label": "❌ Отменить", "value": f"{CALLBACK_PREFIX}{pending_id}:n"},
        ]
    ]
    return TelegramDispatcher(tenant).send(
        action="send_interactive",
        recipient_id=chat_id,
        text=text,
        buttons=buttons,
        reply_to_message_id=reply_to_message_id,
    )
