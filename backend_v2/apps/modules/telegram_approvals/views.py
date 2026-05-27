from __future__ import annotations

import json
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.requests.models import Approval
from apps.modules.requests.approval_workflow import ApprovalDecisionAlreadyMade, confirm_approval_by_id
from apps.modules.telegram_approvals.models import TenantTelegramChat
from apps.modules.telegram_approvals.serializers import MessagingGatewayCallbackSerializer, TenantTelegramChatSerializer
from apps.modules.telegram_approvals.services import deactivate_approval_message_buttons
from apps.tenants.models import Tenant
from apps.tenants.permissions import IsTenantAdmin

logger = logging.getLogger(__name__)


class TenantTelegramChatViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, IsTenantAdmin]
    serializer_class = TenantTelegramChatSerializer

    def get_queryset(self):
        if not hasattr(self.request, "tenant") or self.request.tenant is None:
            return TenantTelegramChat.objects.none()
        return TenantTelegramChat.objects.filter(tenant=self.request.tenant)

    def perform_create(self, serializer):
        try:
            serializer.save(tenant=self.request.tenant, created_by=self.request.user)
        except IntegrityError:
            raise ValidationError({"chat_id": "Telegram-группа с таким Chat ID уже существует."})


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

    def _handle_task_callback(self, payload_str: str, event_data: dict) -> Response:
        """Handle task inline-button callbacks.

        Payload format: "task_<action>_<task_id>"
          task_p_<id>  → move to in_progress
          task_a_<id>  → archive (move to done)
        """
        from apps.modules.tasks.models import Task
        from apps.modules.tasks.services import task_service
        from apps.modules.tasks.notifications.task_notifier import edit_task_notification
        from apps.modules.telegram_approvals.services import get_tenant_bot_token

        parts = payload_str.split("_", 2)
        if len(parts) != 3:
            raise ValidationError({"detail": "Invalid task callback format."})
        action = parts[1]
        try:
            task_id = int(parts[2])
        except (TypeError, ValueError):
            raise ValidationError({"detail": "Invalid task_id in task callback."})

        task = (
            Task.objects.select_related("tenant", "assignee")
            .filter(pk=task_id)
            .first()
        )
        if task is None:
            logger.warning("task_callback: task_id=%s not found", task_id)
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

        # Only the assignee may interact with task buttons.
        from_id = str(event_data.get("user_id") or "").strip()
        assignee_from_id = str(getattr(task.assignee, "telegram_from_id", None) or "")
        if not from_id or from_id != assignee_from_id:
            logger.warning(
                "task_callback: unauthorized user_id=%s expected=%s task_id=%s",
                from_id, assignee_from_id, task_id,
            )
            return Response({"detail": "Not authorized."}, status=status.HTTP_403_FORBIDDEN)

        new_status = Task.STATUS_IN_PROGRESS if action == "p" else Task.STATUS_DONE
        try:
            task = task_service.set_status(task=task, new_status=new_status, actor=task.assignee)
        except Exception:
            logger.info("task_callback: status transition skipped task_id=%s action=%s", task_id, action)

        task.refresh_from_db()

        bot_token = get_tenant_bot_token(task.tenant)
        if bot_token:
            try:
                edit_task_notification(task=task, tenant=task.tenant, bot_token=bot_token)
            except Exception:
                logger.exception("task_callback: edit_task_notification failed task_id=%s", task_id)

        return Response({"detail": "ok"}, status=status.HTTP_200_OK)

    def _handle_invest_pay_callback(self, payload_str: str, event_data: dict) -> Response:
        from apps.modules.investments.models import InvestNotificationConfig, InvestPayoutSchedule
        from apps.modules.investments.notification_services import (
            create_or_get_return_for_schedule,
            remove_payout_notification_button,
        )

        raw_id = payload_str[len("invest_pay:"):]
        try:
            schedule_id = int(raw_id)
        except (TypeError, ValueError):
            raise ValidationError({"detail": "Invalid invest_pay callback: bad schedule_id."})

        message_id = event_data.get("message_id")
        recipient_id = event_data.get("recipient_id")

        schedule = (
            InvestPayoutSchedule.objects
            .select_related("tenant", "company")
            .filter(pk=schedule_id)
            .first()
        )
        if schedule is None:
            raise ValidationError({"detail": "Payout schedule not found."})

        try:
            cfg = InvestNotificationConfig.objects.select_related("responsible_user").get(tenant=schedule.tenant)
        except InvestNotificationConfig.DoesNotExist:
            raise ValidationError({"detail": "Notification config not found for tenant."})

        try:
            from_id = int(event_data["user_id"])
        except (TypeError, ValueError):
            from_id = None
        responsible_tg_id = cfg.responsible_user.telegram_chat_id if cfg.responsible_user else None
        if responsible_tg_id is not None and from_id != responsible_tg_id:
            logger.warning(
                "invest_pay_callback: unauthorized user_id=%s expected=%s schedule_id=%s",
                from_id, responsible_tg_id, schedule_id,
            )
            raise ValidationError({"detail": "Only the responsible user may confirm this payout."})

        with transaction.atomic():
            invest_return, was_created, note = create_or_get_return_for_schedule(
                schedule=schedule, created_by=cfg.responsible_user,
            )

        return_id = invest_return.pk if invest_return is not None else None
        http_status = status.HTTP_201_CREATED if was_created else status.HTTP_200_OK
        if was_created:
            logger.info(
                "invest_pay_callback: created return_id=%s for schedule_id=%s tenant_id=%s",
                return_id, schedule_id, schedule.tenant_id,
            )

        # After commit, drop the button and append the status note (best-effort; the return
        # is already persisted, so an edit failure is cosmetic only).
        try:
            remove_payout_notification_button(
                schedule=schedule, chat_id=recipient_id, message_id=message_id, note=note,
            )
        except Exception:
            logger.exception("invest_pay_callback: button cleanup failed schedule_id=%s", schedule_id)

        return Response({"detail": note, "return_id": return_id}, status=http_status)

    def post(self, request):
        serializer = MessagingGatewayCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event_data = serializer.validated_data

        if event_data.get("event") != "interaction":
            return Response({"detail": "Only interaction events are supported."}, status=status.HTTP_202_ACCEPTED)

        # Investment callbacks: InvestReturn uses "inv_<id>:<a|r>", project investments use "invp_<id>:<a|r>".
        # invp_ must be checked explicitly — "invp_1:a".startswith("inv_") is False (4th char is "p", not "_").
        payload_str = (event_data.get("payload") or "").strip()
        if payload_str.startswith("invp_") or payload_str.startswith("inv_"):
            from apps.modules.investments.views import InvestmentApprovalWebhookView
            return InvestmentApprovalWebhookView().post(request)

        if payload_str.startswith("invest_pay:"):
            return self._handle_invest_pay_callback(payload_str, event_data)

        if payload_str.startswith("task_"):
            return self._handle_task_callback(payload_str, event_data)

        payload_preview = (event_data.get("payload") or "")[:48]
        logger.info(
            "messaging_gateway_webhook interaction user_id=%s recipient_id=%s message_id=%s payload=%r",
            event_data.get("user_id"),
            event_data.get("recipient_id"),
            event_data.get("message_id"),
            payload_preview,
        )

        try:
            parsed_approval_id, decision = self._parse_callback_data(event_data.get("payload"))
        except ValidationError:
            logger.warning(
                "messaging_gateway_webhook bad payload user_id=%s payload=%r",
                event_data.get("user_id"),
                payload_preview,
            )
            raise

        try:
            approval_id = int(parsed_approval_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError({"approval_id": "approval_id is required and must be integer."}) from exc

        try:
            from_id = int(event_data["user_id"])
        except (TypeError, ValueError) as exc:
            raise ValidationError({"user_id": "user_id is required and must be integer."}) from exc
        chat_id = str(event_data["recipient_id"]).strip()
        if not chat_id:
            raise ValidationError({"recipient_id": "recipient_id is required."})
        message_id = event_data.get("message_id")

        approval = (
            Approval.objects.select_related("request", "request__tenant", "approver_user")
            .filter(id=approval_id)
            .first()
        )
        if approval is None:
            logger.warning("messaging_gateway_webhook unknown approval_id=%s", approval_id)
            raise ValidationError({"approval_id": "Approval not found."})
        if message_id is not None and approval.gateway_message_id is not None and approval.gateway_message_id != message_id:
            logger.warning(
                "messaging_gateway_webhook message_id mismatch approval_id=%s stored=%s callback=%s",
                approval_id,
                approval.gateway_message_id,
                message_id,
            )
            raise ValidationError({"message_id": "Callback message_id does not match stored approval message_id."})
        if approval.approver_recipient_id is not None and approval.approver_recipient_id != chat_id:
            logger.warning(
                "messaging_gateway_webhook recipient mismatch approval_id=%s expected=%s got=%s",
                approval_id,
                approval.approver_recipient_id,
                chat_id,
            )
            raise ValidationError({"recipient_id": "Recipient is not allowed for this approval."})
        if approval.approver_external_user_id is not None and approval.approver_external_user_id != from_id:
            logger.warning(
                "messaging_gateway_webhook user mismatch approval_id=%s expected=%s got=%s",
                approval_id,
                approval.approver_external_user_id,
                from_id,
            )
            raise ValidationError({"user_id": "User is not allowed for this approval."})

        tenant: Tenant = approval.request.tenant

        with transaction.atomic():
            if message_id is not None and approval.gateway_message_id is None:
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
                logger.info(
                    "messaging_gateway_webhook duplicate decision approval_id=%s request_id=%s",
                    approval.id,
                    approval.request_id,
                )
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

        logger.info(
            "messaging_gateway_webhook processed approval_id=%s request_id=%s tenant_id=%s decision=%s",
            approval.id,
            approval.request_id,
            tenant.id,
            decision,
        )
        return Response({"detail": "Callback processed."}, status=status.HTTP_200_OK)
