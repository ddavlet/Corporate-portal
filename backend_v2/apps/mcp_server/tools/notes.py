"""MCP tools for the Notes (заметки) module."""

from __future__ import annotations

from typing import Any

from apps.mcp_server.auth import require_module_access
from apps.mcp_server.utils import json_safe

MODULE = "notes"
_MAX_LIMIT = 200


def _user_name(user) -> str:
    return (user.full_name or "").strip() or user.username


def list_my_notes(
    tenant_id: int,
    target_type: str = "",
    target_id: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return notes the current user sent or received (notes are personal messages).

    - target_type: request | cash | bank
    - target_id: id of the request / cash operation / bank operation
    - limit: max records (default 50, max 200), newest first
    """
    user, tenant = require_module_access(tenant_id, MODULE)

    from django.db.models import Q

    from apps.modules.notes.models import Note

    allowed = {c for c, _ in Note.TARGET_TYPE_CHOICES}
    if target_type and target_type not in allowed:
        raise ValueError(f"Invalid target_type {target_type!r}; allowed: {', '.join(sorted(allowed))}")

    qs = (
        Note.objects.filter(tenant=tenant)
        .filter(Q(created_by=user) | Q(recipient_user=user))
        .select_related("created_by", "recipient_user")
    )
    if target_type:
        qs = qs.filter(target_type=target_type)
    if target_id:
        qs = qs.filter(target_id=int(target_id))

    limit = min(max(1, int(limit)), _MAX_LIMIT)
    return json_safe([
        {
            "id": n.id,
            "target_type": n.target_type,
            "target_id": n.target_id,
            "message": n.message,
            "from": _user_name(n.created_by),
            "to": _user_name(n.recipient_user),
            "created_at": n.created_at,
            "delivery_status": n.delivery_status,
        }
        for n in qs.order_by("-created_at", "-id")[:limit]
    ])
