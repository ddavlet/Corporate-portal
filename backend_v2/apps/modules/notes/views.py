from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
import requests

from apps.modules.notes.models import Note
from apps.modules.notes.serializers import NoteCreateSerializer, NoteSerializer, RecipientOptionSerializer
from apps.tenants.integration_settings import get_notes_integration_settings
from apps.tenants.permissions import HasEffectiveModuleAccess

User = get_user_model()


def _target_label(target_type: str, target_id: int) -> str:
    if target_type == Note.TARGET_REQUEST:
        return f"Заявка #{target_id}"
    if target_type == Note.TARGET_CASH:
        return f"Кассовый расход #{target_id}"
    return f"Банковский расход #{target_id}"


def _target_path(*, target_type: str, target_id: int, tenant) -> str:
    cfg = get_notes_integration_settings(tenant=tenant)
    template = cfg.target_path_bank
    if target_type == Note.TARGET_REQUEST:
        template = cfg.target_path_request
    elif target_type == Note.TARGET_CASH:
        template = cfg.target_path_cash
    return template.replace("{id}", str(target_id))


def _send_telegram_message(*, bot_token: str, chat_id: int, text: str, tenant):
    cfg = get_notes_integration_settings(tenant=tenant)
    resp = requests.post(
        f"{cfg.telegram_api_base_url}/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10,
    )
    return resp.ok


class NoteRecipientsView(APIView):
    module_key = "notes"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def get(self, request):
        tenant = request.tenant
        users = User.objects.filter(
            tenantmembership__tenant=tenant,
            tenantmembership__is_active=True,
            telegram_chat_id__isnull=False,
        ).order_by("full_name", "username")
        serializer = RecipientOptionSerializer(users, many=True)
        return Response({"items": serializer.data})


class NotesCreateView(APIView):
    module_key = "notes"
    permission_classes = [IsAuthenticated, HasEffectiveModuleAccess]

    def post(self, request):
        tenant = request.tenant
        serializer = NoteCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        note = Note.objects.create(
            tenant=tenant,
            created_by=request.user,
            recipient_user=serializer.validated_data["recipient_user"],
            target_type=serializer.validated_data["target_type"],
            target_id=serializer.validated_data["target_id"],
            message=serializer.validated_data["message"],
            delivery_status=Note.DELIVERY_PENDING,
        )

        recipient = note.recipient_user
        sender_name = (request.user.full_name or "").strip() or request.user.username
        recipient_name = (recipient.full_name or "").strip() or recipient.username
        target_label = _target_label(note.target_type, note.target_id)
        target_url = request.build_absolute_uri(_target_path(target_type=note.target_type, target_id=note.target_id, tenant=tenant))
        text = (
            "Новая заметка\n\n"
            f"От: {sender_name}\n"
            f"Кому: {recipient_name}\n"
            f"Запись: {target_label}\n\n"
            f"Текст заметки:\n{note.message}\n\n"
            f"Открыть запись: {target_url}"
        )

        bot_token = tenant.get_telegram_bot_token()
        delivery_error = ""
        sent = False
        if not bot_token:
            delivery_error = "Токен Telegram-бота не настроен для компании."
        elif not recipient.telegram_chat_id:
            delivery_error = "У получателя не настроен telegram_chat_id."
        else:
            try:
                sent = _send_telegram_message(
                    bot_token=bot_token,
                    chat_id=recipient.telegram_chat_id,
                    text=text,
                    tenant=tenant,
                )
                if not sent:
                    delivery_error = "Telegram API вернул ошибку при отправке."
            except Exception as exc:  # noqa: BLE001
                delivery_error = str(exc)
                sent = False

        if sent:
            note.delivery_status = Note.DELIVERY_SENT
            note.sent_at = timezone.now()
            note.delivery_error = ""
            note.save(update_fields=["delivery_status", "sent_at", "delivery_error"])
        else:
            note.delivery_status = Note.DELIVERY_FAILED
            note.delivery_error = delivery_error[:1000]
            note.save(update_fields=["delivery_status", "delivery_error"])

        return Response(
            {
                "note": NoteSerializer(note).data,
                "delivery": {"status": note.delivery_status, "error": note.delivery_error or None},
            },
            status=status.HTTP_201_CREATED,
        )
