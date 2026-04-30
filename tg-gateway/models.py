from __future__ import annotations
from typing import Any
from pydantic import BaseModel, field_validator

SEND_ACTIONS   = {"send", "send_interactive"}
EDIT_ACTIONS   = {"edit", "edit_interactive"}
DELETE_ACTIONS = {"delete"}
ALL_ACTIONS    = SEND_ACTIONS | EDIT_ACTIONS | DELETE_ACTIONS

# Universal format → Telegram parse_mode
_FORMAT_TO_TG: dict[str, str | None] = {
    "html":     "HTML",
    "markdown": "Markdown",
    "plain":    None,
}


class Button(BaseModel):
    label: str
    value: str = ""
    url: str | None = None


class DispatchRequest(BaseModel):
    action:       str
    bot_token:    str
    tenant_id:    str | None = None
    recipient_id: str                           # platform-agnostic chat/channel/user ID
    text:         str | None = None
    format:       str = "html"                  # html | markdown | plain
    message_id:   int | None = None
    buttons:      list[list[Button]] = []       # [[{label, value}, ...], ...]
    request_id:   int | None = None
    approval_id:  str | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        if v not in ALL_ACTIONS:
            raise ValueError(f"Unknown action '{v}'. Known: {sorted(ALL_ACTIONS)}")
        return v

    def tg_recipient(self) -> int:
        """Convert universal recipient_id (str) to Telegram chat_id (int)."""
        return int(self.recipient_id)

    def tg_parse_mode(self) -> str | None:
        """Convert universal format to Telegram parse_mode."""
        return _FORMAT_TO_TG.get(self.format.lower(), "HTML")

    def tg_keyboard(self) -> list[list[dict[str, Any]]]:
        """Convert universal buttons to Telegram inline_keyboard format."""
        result = []
        for row in self.buttons:
            tg_row = []
            for btn in row:
                if btn.url:
                    tg_row.append({"text": btn.label, "url": btn.url})
                else:
                    tg_row.append({"text": btn.label, "callback_data": btn.value})
            result.append(tg_row)
        return result
