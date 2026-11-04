"""Страховка от Markdown в ответе модели.

Ответ уходит в Telegram как HTML, и промпт требует HTML, но модель иногда пишет
Markdown: **жирный**, `код`, «- » в начале строки. Здесь самые частые конструкции
переводятся в HTML до санитайзера; содержимое <pre>/<code> не трогается.
"""

import re

# Уже размеченные блоки, внутри которых ничего не меняем.
_PROTECTED_RE = re.compile(r"(<pre\b[^>]*>.*?</pre>|<code\b[^>]*>.*?</code>)", re.IGNORECASE | re.DOTALL)
_FENCE_RE = re.compile(r"```[^\n`]*\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)")
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^([ \t]*)[-*][ \t]+", re.MULTILINE)


def _convert_plain(segment: str) -> str:
    parts = _INLINE_CODE_RE.split(segment)
    out = []
    # Нечётные элементы — содержимое `кода`, его не размечаем.
    for i, part in enumerate(parts):
        if i % 2:
            out.append(f"<code>{part}</code>")
            continue
        part = _HEADING_RE.sub(r"<b>\1</b>", part)
        part = _BULLET_RE.sub(r"\1• ", part)
        part = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", part)
        out.append(part)
    return "".join(out)


def _convert_outside_fences(text: str) -> str:
    out = []
    pos = 0
    for m in _FENCE_RE.finditer(text):
        out.append(_convert_plain(text[pos:m.start()]))
        out.append(f"<pre>{m.group(1).rstrip()}</pre>")
        pos = m.end()
    out.append(_convert_plain(text[pos:]))
    return "".join(out)


def markdown_to_telegram_html(text: str) -> str:
    """Переводит частый Markdown в теги Telegram HTML; существующий HTML сохраняется."""
    if not text:
        return ""
    pieces = _PROTECTED_RE.split(text)
    # Нечётные элементы — уже размеченные <pre>/<code>.
    return "".join(piece if i % 2 else _convert_outside_fences(piece) for i, piece in enumerate(pieces))
