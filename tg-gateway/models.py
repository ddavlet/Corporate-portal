from __future__ import annotations
from typing import Any
from pydantic import BaseModel, field_validator

SEND_ACTIONS   = {"send_message", "send_message_button"}
EDIT_ACTIONS   = {"edit_message", "edit_message_button"}
DELETE_ACTIONS = {"delete_message"}
ALL_ACTIONS    = SEND_ACTIONS | EDIT_ACTIONS | DELETE_ACTIONS


class DispatchRequest(BaseModel):
    action: str
    bot_token: str
    tenant_id: str | None = None
    chat_id: int
    text_message: str | None = None
    parse_mode: str = "HTML"
    message_id: int | None = None
    inline_keyboard: list[list[dict[str, Any]]] = []
    request_id: int | None = None
    approval_id: str | None = None

    @field_validator("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        if v not in ALL_ACTIONS:
            raise ValueError(f"Unknown action '{v}'. Known: {sorted(ALL_ACTIONS)}")
        return v
