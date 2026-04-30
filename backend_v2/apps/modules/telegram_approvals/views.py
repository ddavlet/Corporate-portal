from __future__ import annotations

import json

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.requests.models import Approval
from apps.modules.requests.approval_workflow import ApprovalDecisionAlreadyMade, confirm_approval_by_id
from apps.modules.telegram_approvals.serializers import MessagingGatewayCallbackSerializer
from apps.modules.telegram_approvals.services import deactivate_approval_message_buttons
from apps.tenants.models import Tenant


class TelegramApprovalWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def _parse_callback_data(self, callback_data: str | None) -> tuple[int | None, str]:
        if not callback_data:
            raise ValidationError({"detail": "payload (callback data) is required."})
        raw = callback_data.strip()
        # Some setups JSON-encode the callback value: "\"v2_2267:a\""
        if raw.startswith('"') and raw.endswith('"'):
            try:
                decoded_raw = json.loads(raw)
                if isinstance(decoded_raw, str):
                    raw = decoded_raw.strip()
            except json.JSONDecodeError:
                pass
        # Compact format: "v2_<approval_id>:<a|r>"
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

        # Backward-compatible JSON payload format
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError({"detail": "payload must be valid JSON or compact v2_<id>:<a|r> format."}) from exc
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
        raise ValidationError({"detail": "Unsupported decision value in callback payload."})

    def post(self, request):
        serializer = MessagingGatewayCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event_data = serializer.validated_data

        if event_data.get("event") != "interaction":
            return Response({"detail": "Only interaction events are supported."}, status=status.HTTP_202_ACCEPTED)

        parsed_approval_id, decision = self._parse_callback_data(event_data.get("payload"))

        try:
            approval_id = int(parsed_approval_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"approval_id": "approval_id is required and must be integer."}) from exc

        try:
            from_id = int(event_data["user_id"])
        except (TypeError, ValueError) as exc:
            raise ValidationError({"user_id": "user_id is required and must be integer."}) from exc
        try:
            chat_id = int(event_data["recipient_id"])
        except (TypeError, ValueError) as exc:
            raise ValidationError({"recipient_id": "recipient_id is required and must be integer."}) from exc
        message_id = event_data["message_id"]

        approval = (
            Approval.objects.select_related("request", "request__tenant", "approver_user")
            .filter(id=approval_id)
            .first()
        )
        if approval is None:
            raise ValidationError({"approval_id": "Approval not found."})
        if approval.gateway_message_id and approval.gateway_message_id != message_id:
            raise ValidationError({"message_id": "Callback message_id does not match stored approval message_id."})
        if approval.approver_recipient_id is not None and approval.approver_recipient_id != chat_id:
            raise ValidationError({"recipient_id": "Recipient is not allowed for this approval."})
        if approval.approver_external_user_id is not None and approval.approver_external_user_id != from_id:
            raise ValidationError({"user_id": "User is not allowed for this approval."})

        tenant: Tenant = approval.request.tenant

        with transaction.atomic():
            if approval.gateway_message_id is None:
                updates = ["gateway_message_id"]
                approval.gateway_message_id = message_id
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
                    approver_recipient_id=chat_id,
                    approver_external_user_id=from_id,
                    decision=decision,
                )
            except ApprovalDecisionAlreadyMade:
                approval.refresh_from_db()
                approval.request.refresh_from_db()
                updated = deactivate_approval_message_buttons(
                    approval=approval,
                    request_context=approval.request,
                )
                if not updated and message_id:
                    # Fallback for legacy rows where approval message id was not persisted
                    approval.gateway_message_id = message_id
                    deactivate_approval_message_buttons(approval=approval, request_context=approval.request)
                raise

        return Response({"detail": "Callback processed."}, status=status.HTTP_200_OK)
