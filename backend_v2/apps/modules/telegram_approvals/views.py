from __future__ import annotations

import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.requests.models import Approval
from apps.modules.requests.approval_workflow import ApprovalDecisionAlreadyMade, confirm_approval_by_id
from apps.modules.telegram_approvals.serializers import TelegramApprovalWebhookSerializer
from apps.modules.telegram_approvals.services import (
    build_approval_message,
    deactivate_approval_message_buttons,
    post_telegram_bridge,
)
from apps.modules.requests.integration_settings import get_requests_telegram_integration_settings
from apps.tenants.models import Tenant


class TelegramApprovalWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def _check_token(self, request):
        tenant = getattr(request, "tenant", None)
        expected = get_requests_telegram_integration_settings(tenant=tenant).n8n_integration_token
        if not expected:
            expected = (getattr(settings, "N8N_INTEGRATION_TOKEN", "") or "").strip()
        if not expected:
            return
        got = (request.META.get("HTTP_X_N8N_INTEGRATION_TOKEN", "") or "").strip()
        if got != expected:
            raise ValidationError({"detail": "Invalid webhook token."})

    def _extract_update(self, payload: dict) -> dict:
        if isinstance(payload.get("update"), dict):
            return payload["update"]
        return payload

    def _parse_callback_data(self, callback_data: str | None) -> tuple[int | None, str]:
        if not callback_data:
            raise ValidationError({"detail": "callback_query.data is required."})
        raw = callback_data.strip()
        # Some bridge setups can pass callback_data as JSON-encoded string,
        # e.g. "\"v2_2267:a\"" or "\"2267:a\"".
        if raw.startswith('"') and raw.endswith('"'):
            try:
                decoded_raw = json.loads(raw)
                if isinstance(decoded_raw, str):
                    raw = decoded_raw.strip()
            except json.JSONDecodeError:
                pass
        # New compact format: "v2_<approval_id>:<a|r>"
        if raw.startswith("v2_"):
            compact = raw[3:]
            if ":" in compact and compact.count(":") == 1:
                left, right = compact.split(":", 1)
                try:
                    approval_id = int(left)
                except (TypeError, ValueError):
                    approval_id = None
                code = right.strip().lower()
                if code == "a":
                    return approval_id, Approval.DECISION_APPROVED
                if code == "r":
                    return approval_id, Approval.DECISION_REJECTED

        # Transitional compact format (without prefix): "<approval_id>:<a|r>"
        if ":" in raw and raw.count(":") == 1:
            left, right = raw.split(":", 1)
            try:
                approval_id = int(left)
            except (TypeError, ValueError):
                approval_id = None
            code = right.strip().lower()
            if code == "a":
                return approval_id, Approval.DECISION_APPROVED
            if code == "r":
                return approval_id, Approval.DECISION_REJECTED

        # Backward compatible format: JSON payload.
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError({"detail": "callback_query.data must be valid JSON."}) from exc
        raw_decision = (parsed.get("decision") or "").strip().lower()
        raw_approval_id = parsed.get("approval_id")
        try:
            approval_id = int(raw_approval_id) if raw_approval_id not in (None, "") else None
        except (TypeError, ValueError):
            approval_id = None
        if raw_decision == "approved":
            return approval_id, Approval.DECISION_APPROVED
        if raw_decision == "rejected":
            return approval_id, Approval.DECISION_REJECTED
        raise ValidationError({"detail": "Unsupported decision value in callback data."})

    def post(self, request):
        self._check_token(request)
        serializer = TelegramApprovalWebhookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data
        update = self._extract_update(payload)
        callback_query = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else None
        if callback_query is None:
            return Response({"detail": "Only callback_query updates are supported."}, status=status.HTTP_202_ACCEPTED)

        parsed_approval_id, decision = self._parse_callback_data(callback_query.get("data"))
        raw_approval_id = callback_query.get("approval_id")
        if raw_approval_id in (None, ""):
            raw_approval_id = parsed_approval_id
        try:
            approval_id = int(raw_approval_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"approval_id": "approval_id is required and must be integer."}) from exc

        from_obj = callback_query.get("from") if isinstance(callback_query.get("from"), dict) else {}
        message_obj = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
        chat_obj = message_obj.get("chat") if isinstance(message_obj.get("chat"), dict) else {}

        try:
            from_id = int(from_obj.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"from_id": "callback_query.from.id is required and must be integer."}) from exc
        try:
            chat_id = int(chat_obj.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"chat_id": "callback_query.message.chat.id is required and must be integer."}) from exc
        try:
            message_id = int(message_obj.get("message_id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError({"message_id": "callback_query.message.message_id is required and must be integer."}) from exc

        approval = (
            Approval.objects.select_related("request", "request__tenant", "approver_user")
            .filter(id=approval_id)
            .first()
        )
        if approval is None:
            raise ValidationError({"approval_id": "Approval not found."})
        if approval.message_id and approval.message_id != message_id:
            raise ValidationError({"message_id": "Callback message_id does not match stored approval message_id."})
        if approval.approver_tg_id is not None and approval.approver_tg_id != chat_id:
            raise ValidationError({"chat_id": "Chat is not allowed for this approval."})
        if approval.approver_tg_from_id is not None and approval.approver_tg_from_id != from_id:
            raise ValidationError({"from_id": "User is not allowed for this approval."})

        tenant: Tenant = approval.request.tenant

        with transaction.atomic():
            if approval.message_id is None:
                updates = ["message_id"]
                approval.message_id = message_id
                if not approval.message_sent:
                    approval.message_sent = True
                    updates.append("message_sent")
                if approval.message_sent_at is None:
                    approval.message_sent_at = timezone.now()
                    updates.append("message_sent_at")
                approval.save(update_fields=updates)
            try:
                confirm_approval_by_id(
                    tenant=tenant,
                    approval_id=approval.id,
                    request_id=approval.request_id,
                    approver_tg_id=chat_id,
                    approver_tg_from_id=from_id,
                    decision=decision,
                )
            except ApprovalDecisionAlreadyMade:
                # Keep HTTP 409, but still try to sync stale Telegram card to current
                # state and remove action buttons.
                approval.refresh_from_db()
                approval.request.refresh_from_db()
                updated = deactivate_approval_message_buttons(
                    approval=approval,
                    request_context=approval.request,
                )
                if not updated and chat_id and message_id:
                    # Fallback for legacy rows where approval.message_id was not persisted:
                    # use callback message identifiers to force an edit attempt.
                    payload = {
                        "action": get_requests_telegram_integration_settings(tenant=tenant).edit_action,
                        "message": build_approval_message(request_obj=approval.request, approval=approval),
                        "parse_mode": "HTML",
                        "chat_id": chat_id,
                        "company": approval.request.company_payer or "",
                        "approval_id": approval.id,
                        "request_id": approval.request_id,
                        "message_id": message_id,
                        "inline_keyboard": [],
                    }
                    post_telegram_bridge(tenant=tenant, payload=payload)
                raise

        return Response({"detail": "Callback processed."}, status=status.HTTP_200_OK)

