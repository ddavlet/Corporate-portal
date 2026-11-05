import logging

from django.db import transaction

from apps.modules.telegram_approvals.command_handlers import resolve_tenant_by_bot_id

from .access import REASON_OK, assistant_enabled, portal_identity, resolve_assistant_user
from .chain import add_node, ensure_parent, find_known_node, get_or_create_node, user_label
from .jobs import submit_turn
from .models import ChainNode
from .serializers import AssistantMessageEventSerializer

logger = logging.getLogger(__name__)

IGNORED = ({"status": "ignored"}, 200)
STORED = ({"status": "stored"}, 200)
ACCEPTED = ({"status": "accepted"}, 202)


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _store_member(tenant, chat_id, tg_id, event):
    user, roles = portal_identity(tenant, tg_id)
    label = user_label(user) if user is not None else (event.get("sender_name") or "")
    add_node(
        tenant=tenant,
        chat_id=chat_id,
        message_id=event["message_id"],
        parent_message_id=event.get("reply_to_message_id"),
        kind=ChainNode.KIND_MEMBER,
        text=event["payload"],
        author_user=user,
        author_tg_id=tg_id,
        author_label=label,
        author_roles=roles,
    )


def handle_message_event(data: dict) -> tuple[dict, int]:
    """Decide silently whether the sender may talk to the assistant; store and schedule. Never replies."""
    serializer = AssistantMessageEventSerializer(data=data)
    if not serializer.is_valid():
        logger.warning(
            "ai_assistant: invalid message event, fields=%s", sorted(serializer.errors.keys())
        )
        return IGNORED
    event = serializer.validated_data

    tenant = resolve_tenant_by_bot_id(event.get("bot_id"))
    if tenant is None or not assistant_enabled(tenant):
        return IGNORED

    chat_id = str(event["recipient_id"]).strip()
    tg_id = _to_int(event["user_id"])
    if tg_id is None:
        logger.warning(
            "ai_assistant: rejected reason=not_member tenant=%s tg_user=%r chat=%s (non-numeric user id)",
            tenant.pk, event["user_id"], chat_id,
        )
        return IGNORED

    chat_type = event.get("chat_type") or ""
    is_group_reply = chat_type != "private" and bool(event.get("reply_to_message_id"))
    addressed = chat_type == "private" or event.get("mentions_bot") or event.get("reply_to_is_bot")

    with transaction.atomic():
        if not addressed:
            if is_group_reply and find_known_node(tenant, chat_id, event["reply_to_message_id"]) is not None:
                _store_member(tenant, chat_id, tg_id, event)
                return STORED
            return IGNORED

        access = resolve_assistant_user(tenant, tg_id)
        if access.reason != REASON_OK:
            logger.warning(
                "ai_assistant: rejected reason=%s tenant=%s tg_user=%s chat=%s",
                access.reason, tenant.pk, tg_id, chat_id,
            )
            if is_group_reply and find_known_node(tenant, chat_id, event["reply_to_message_id"]) is not None:
                _store_member(tenant, chat_id, tg_id, event)
                return STORED
            return IGNORED

        ensure_parent(tenant, chat_id, event)
        node, created = get_or_create_node(
            tenant=tenant,
            chat_id=chat_id,
            message_id=event["message_id"],
            parent_message_id=event.get("reply_to_message_id"),
            kind=ChainNode.KIND_USER,
            text=event["payload"],
            author_user=access.user,
            author_tg_id=tg_id,
            author_label=user_label(access.user),
            author_roles=",".join(sorted(access.roles)),
        )
        if not created:
            # Повторная доставка того же сообщения Telegram: ход уже запущен, второй ответ не нужен.
            logger.info(
                "ai_assistant: duplicate message ignored tenant=%s chat=%s message_id=%s",
                tenant.pk, chat_id, event["message_id"],
            )
            return ACCEPTED
        if chat_type == "private":
            submit_turn(node.id)
        else:
            submit_turn(node.id, addressee_check={"mentions_bot": bool(event.get("mentions_bot"))})
    return ACCEPTED
