from __future__ import annotations

import logging

import requests
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.modules.feedback.models import PortalFeedback
from apps.modules.feedback.services import (
    build_portal_feedback_dispatch_payload,
    build_portal_feedback_telegram_message,
    post_feedback_ai_refine,
)
from apps.modules.telegram_approvals.services import post_messaging_gateway
from apps.tenants.integration_settings import get_portal_feedback_settings

logger = logging.getLogger(__name__)


class FeedbackAiRefineSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[PortalFeedback.KIND_ERROR, PortalFeedback.KIND_IMPROVEMENT])
    text = serializers.CharField(allow_blank=False, trim_whitespace=True)


class FeedbackSubmitSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[PortalFeedback.KIND_ERROR, PortalFeedback.KIND_IMPROVEMENT])
    body = serializers.CharField(allow_blank=False, trim_whitespace=True)
    page_path = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class MyFeedbackSerializer(serializers.ModelSerializer):
    work_status_label = serializers.CharField(source="get_work_status_display", read_only=True)

    class Meta:
        model = PortalFeedback
        fields = (
            "id",
            "kind",
            "body",
            "page_path",
            "work_status",
            "work_status_label",
            "created_at",
            "resolved_at",
        )
        read_only_fields = fields


class FeedbackAiRefineView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = FeedbackAiRefineSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        body = {
            "action": "feedback_former",
            "payload": {
                "kind": ser.validated_data["kind"],
                "text": ser.validated_data["text"],
            },
        }
        try:
            feedback_text = post_feedback_ai_refine(tenant=tenant, body=body)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except requests.HTTPError as exc:
            resp = exc.response
            req_url = getattr(getattr(exc, "request", None), "url", None)
            if resp is not None:
                logger.warning(
                    "Feedback AI webhook HTTP %s url=%s body_prefix=%r",
                    resp.status_code,
                    req_url,
                    (resp.text or "")[:500],
                )
            detail = (
                f"Вебхук n8n для ИИ вернул HTTP {resp.status_code}. Проверьте workflow на пути webhook/{tenant.subdomain}/…"
                if resp is not None
                else str(exc)
            )
            return Response({"detail": detail}, status=status.HTTP_502_BAD_GATEWAY)
        except requests.RequestException as exc:
            logger.exception("Feedback AI refine failed")
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response({"feedback": feedback_text})


class FeedbackSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = FeedbackSubmitSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        kind = ser.validated_data["kind"]
        body = ser.validated_data["body"]
        page_path = (ser.validated_data.get("page_path") or "").strip()[:500]

        fb = PortalFeedback.objects.create(
            tenant=tenant,
            created_by=request.user,
            kind=kind,
            body=body,
            page_path=page_path,
        )

        pf = get_portal_feedback_settings(tenant=tenant)
        kind_label = "Ошибка" if kind == PortalFeedback.KIND_ERROR else "Улучшение"
        author = (request.user.full_name or "").strip() or request.user.username

        if pf.recipient_id is None:
            fb.delivery_status = PortalFeedback.DELIVERY_SKIPPED
            fb.delivery_error = "Получатель messaging gateway не настроен (messaging_gateway_feedback_recipient_id)."
            fb.save(update_fields=["delivery_status", "delivery_error"])
            return Response(
                {
                    "id": fb.id,
                    "delivery": {"status": fb.delivery_status, "error": None},
                },
                status=status.HTTP_201_CREATED,
            )

        message_html = build_portal_feedback_telegram_message(
            feedback_id=fb.pk,
            kind=kind,
            kind_label=kind_label,
            author_display=author,
            page_path=page_path,
            body=body,
        )
        dispatch_payload = build_portal_feedback_dispatch_payload(
            action=pf.action,
            chat_id=int(pf.recipient_id),
            message_html=message_html,
            feedback_id=fb.pk,
            kind=kind,
            tenant=tenant,
        )
        bridge_result = post_messaging_gateway(tenant=tenant, payload=dispatch_payload)
        if bridge_result is not None:
            fb.delivery_status = PortalFeedback.DELIVERY_SENT
            fb.delivery_error = ""
            fb.sent_at = timezone.now()
            fb.save(update_fields=["delivery_status", "delivery_error", "sent_at"])
            return Response(
                {
                    "id": fb.id,
                    "delivery": {"status": fb.delivery_status, "error": None},
                },
                status=status.HTTP_201_CREATED,
            )

        fb.delivery_status = PortalFeedback.DELIVERY_FAILED
        fb.delivery_error = "Не удалось отправить сообщение через messaging gateway."
        fb.save(update_fields=["delivery_status", "delivery_error"])
        return Response(
            {
                "id": fb.id,
                "delivery": {"status": fb.delivery_status, "error": fb.delivery_error},
            },
            status=status.HTTP_201_CREATED,
        )


class MyFeedbackListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if not tenant:
            return Response({"detail": "Unknown tenant."}, status=status.HTTP_404_NOT_FOUND)

        qs = (
            PortalFeedback.objects.filter(tenant=tenant, created_by=request.user)
            .order_by("-created_at")[:100]
        )
        data = MyFeedbackSerializer(qs, many=True).data
        return Response({"results": data})
