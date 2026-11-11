import logging
import re
from collections import OrderedDict

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from apps.modules.requests.models import Approval, Request, UserRequestApproval
from apps.modules.telegram_approvals.models import Notification, TelegramMessage, TelegramMessageHistory
from apps.modules.telegram_approvals.services import TelegramDispatcher

logger = logging.getLogger(__name__)

_SPLIT_RE = re.compile(r"[,\s]+")


def _parse_ids(values, flag: str) -> list[int]:
    """Values from repeated flags, each may hold several ids separated by commas/spaces."""
    ids: list[int] = []
    for raw in values or []:
        for part in _SPLIT_RE.split(str(raw).strip()):
            if not part:
                continue
            if not part.isdigit():
                raise CommandError(f"{flag}: ожидаются числовые id, получено {part!r}")
            ids.append(int(part))
    return list(dict.fromkeys(ids))


class Command(BaseCommand):
    help = (
        "Удалить сообщения ботов в Telegram через tg-gateway по pk TelegramMessage "
        "и/или по номеру заявки (в т.ч. удалённой). По умолчанию dry-run; --apply удаляет. "
        "Строки БД не удаляются: пишется только история action=delete. "
        "Источник history (request_id в истории отправок) берётся только из тенанта заявки и только для "
        "сообщений, не привязанных к другим сущностям (инвестиции, касса, задачи и т.п.); если заявки нет "
        "в БД, такие сообщения не подтверждены и удаляются только с --unconfirmed-history. "
        "Сообщения, удалённые в Telegram ответом «-» владельца, бэкенд не отслеживает: команда попытается "
        "удалить их снова и покажет ошибку gateway (Telegram: message to delete not found). "
        "На production: make delete-telegram-messages MESSAGE_PKS=… REQUEST_IDS=… [APPLY=1] [UNCONFIRMED_HISTORY=1]."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--message-pk",
            action="append",
            default=[],
            help="pk TelegramMessage; флаг можно повторять, значения — через запятую",
        )
        parser.add_argument(
            "--request-id",
            action="append",
            default=[],
            help="ID заявки (Request.pk); флаг можно повторять, значения — через запятую",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Реально удалить сообщения (без флага — только показать)",
        )
        parser.add_argument(
            "--unconfirmed-history",
            action="store_true",
            help="Удалять и неподтверждённые сообщения из истории (заявки нет в БД, тенант не проверить)",
        )

    def handle(self, *args, **options):
        message_pks = _parse_ids(options["message_pk"], "--message-pk")
        request_ids = _parse_ids(options["request_id"], "--request-id")
        if not message_pks and not request_ids:
            raise CommandError("Укажите --message-pk и/или --request-id (например: --message-pk 15924 --request-id 9142)")

        errors = 0
        candidates: "OrderedDict[int, dict]" = OrderedDict()

        def add(message: TelegramMessage, source: str, *, unconfirmed: bool = False) -> None:
            entry = candidates.setdefault(message.pk, {"message": message, "sources": [], "unconfirmed": True})
            if source not in entry["sources"]:
                entry["sources"].append(source)
            # Confirmed by any source → confirmed.
            entry["unconfirmed"] = entry["unconfirmed"] and unconfirmed

        if message_pks:
            found = TelegramMessage.objects.select_related("tenant").in_bulk(message_pks)
            for pk in message_pks:
                message = found.get(pk)
                if message is None:
                    self.stderr.write(self.style.ERROR(f"TelegramMessage pk={pk}: не найдено"))
                    errors += 1
                    continue
                add(message, "message_pk")

        if request_ids:
            by_request = self._messages_for_requests(request_ids)
            for rid in request_ids:
                items = by_request.get(rid, [])
                for item in items:
                    add(item["message"], item["source"], unconfirmed=item.get("unconfirmed", False))
                if not items:
                    self.stderr.write(self.style.WARNING(f"Request id={rid}: сообщений не найдено"))

        # Deleted = a successful delete of the *current* Telegram message_id: resend() reuses the
        # TelegramMessage row with a new message_id, and that new message is not deleted yet.
        deleted_pairs = set(
            TelegramMessageHistory.objects.filter(
                telegram_message_id__in=list(candidates),
                action=TelegramMessageHistory.ACTION_DELETE,
                success=True,
            ).values_list("telegram_message_id", "message_id")
        )
        already_deleted = {
            pk for pk, entry in candidates.items() if (pk, entry["message"].message_id) in deleted_pairs
        }
        unconfirmed_skipped = set()
        if not options["unconfirmed_history"]:
            unconfirmed_skipped = {
                pk for pk, entry in candidates.items() if entry["unconfirmed"] and pk not in already_deleted
            }

        for pk, entry in candidates.items():
            message = entry["message"]
            mark = " [уже удалено]" if pk in already_deleted else ""
            if entry["unconfirmed"] and pk not in already_deleted:
                mark += " [не подтверждено: заявки нет в БД, тенант не проверен]"
            self.stdout.write(
                f"TelegramMessage pk={pk} tenant={message.tenant_id}:{getattr(message.tenant, 'subdomain', '')} "
                f"recipient_id={message.recipient_id} message_id={message.message_id} "
                f"sent_at={message.sent_at.isoformat() if message.sent_at else '-'} "
                f"источники={','.join(entry['sources'])}{mark}"
            )

        to_delete = [
            entry["message"]
            for pk, entry in candidates.items()
            if pk not in already_deleted and pk not in unconfirmed_skipped
        ]

        if unconfirmed_skipped:
            self.stderr.write(self.style.WARNING(
                f"Неподтверждённых сообщений из истории: {len(unconfirmed_skipped)} — они могут относиться к другой "
                "сущности или другому тенанту и не будут удалены. Проверьте их и добавьте --unconfirmed-history."
            ))

        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS(
                f"Dry-run. Будет удалено: {len(to_delete)}, пропущено (уже удалено): {len(already_deleted)}, "
                f"пропущено (не подтверждено): {len(unconfirmed_skipped)}. "
                "Для удаления добавьте --apply."
            ))
            if errors:
                raise CommandError(f"Ошибок: {errors}")
            return

        for pk in sorted(already_deleted):
            self.stdout.write(f"TelegramMessage pk={pk}: пропущено (уже удалено)")
        for pk in sorted(unconfirmed_skipped):
            self.stdout.write(f"TelegramMessage pk={pk}: пропущено (не подтверждено)")

        deleted = 0
        dispatchers: dict[int, TelegramDispatcher] = {}
        for message in to_delete:
            try:
                dispatcher = dispatchers.get(message.tenant_id)
                if dispatcher is None:
                    dispatcher = dispatchers[message.tenant_id] = TelegramDispatcher(message.tenant)
                if not dispatcher.bot_token:
                    self.stderr.write(self.style.ERROR(
                        f"TelegramMessage pk={message.pk}: у тенанта id={message.tenant_id} нет токена бота"
                    ))
                    errors += 1
                    continue
                last_pk = (
                    TelegramMessageHistory.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
                )
                dispatcher.delete(message)
                record = (
                    TelegramMessageHistory.objects.filter(
                        telegram_message=message,
                        action=TelegramMessageHistory.ACTION_DELETE,
                        pk__gt=last_pk,
                    )
                    .order_by("-pk")
                    .first()
                )
                if record is not None and record.success:
                    deleted += 1
                    self.stdout.write(self.style.SUCCESS(f"TelegramMessage pk={message.pk}: удалено"))
                else:
                    errors += 1
                    self.stderr.write(self.style.ERROR(
                        f"TelegramMessage pk={message.pk}: gateway вернул ошибку (см. логи backend_v2 и tg-gateway)"
                    ))
            except Exception:
                logger.exception("delete_telegram_messages: failed telegram_message_id=%s", message.pk)
                errors += 1
                self.stderr.write(self.style.ERROR(f"TelegramMessage pk={message.pk}: исключение (см. логи backend_v2)"))

        summary = (
            f"Удалено: {deleted}, ошибок: {errors}, пропущено (уже удалено): {len(already_deleted)}, "
            f"пропущено (не подтверждено): {len(unconfirmed_skipped)}"
        )
        if errors:
            raise CommandError(summary)
        self.stdout.write(self.style.SUCCESS(summary))

    @staticmethod
    def _messages_for_requests(rids: list[int]) -> dict[int, list[dict]]:
        """Map request id → [{"message", "source", "unconfirmed"}] for every linked TelegramMessage.

        Direct links (Approval, UserRequestApproval, Notification) are trusted. The history source
        (request_payload.request_id) is ambiguous: investment approval cards also send
        request_id=<InvestReturn/ProjectInvestment id>, and ids repeat across tenants. So a message found
        only through history is kept only if it belongs to the request's tenant and is not linked to any
        other entity; if the request row is gone, its tenant is unknown and the message is unconfirmed.
        """
        result: dict[int, list[dict]] = {rid: [] for rid in rids}
        direct: dict[int, set[int]] = {rid: set() for rid in rids}

        def put(rid: int, message: TelegramMessage, source: str, unconfirmed: bool = False) -> None:
            result[rid].append({"message": message, "source": source, "unconfirmed": unconfirmed})

        for model, source in ((Approval, "approval"), (UserRequestApproval, "user_approval")):
            rows = (
                model.objects.filter(request_id__in=rids, telegram_message__isnull=False)
                .select_related("telegram_message__tenant")
                .order_by("pk")
            )
            for row in rows:
                direct[row.request_id].add(row.telegram_message_id)
                put(row.request_id, row.telegram_message, source)

        request_ct = ContentType.objects.get_for_model(Request)
        notifications = (
            Notification.objects.filter(content_type=request_ct, object_id__in=rids, telegram_message__isnull=False)
            .select_related("telegram_message__tenant")
            .order_by("pk")
        )
        for row in notifications:
            direct[row.object_id].add(row.telegram_message_id)
            put(row.object_id, row.telegram_message, "notification")

        # One query for all ids; request_id is stored as int or str depending on the sender.
        history_rows = (
            TelegramMessageHistory.objects.filter(
                Q(request_payload__request_id__in=rids) | Q(request_payload__request_id__in=[str(r) for r in rids])
            )
            .order_by()
            .values_list("telegram_message_id", "request_payload__request_id")
            .distinct()
        )
        history_pks: dict[int, set[int]] = {rid: set() for rid in rids}
        for message_pk, raw_rid in history_rows:
            try:
                rid = int(raw_rid)
            except (TypeError, ValueError):
                continue
            if rid in history_pks and message_pk is not None:
                history_pks[rid].add(message_pk)
        all_history_pks = set().union(*history_pks.values())
        if not all_history_pks:
            return result

        messages = TelegramMessage.objects.select_related("tenant").in_bulk(list(all_history_pks))
        linked_elsewhere = Command._linked_message_pks(all_history_pks)
        request_tenants = dict(Request.all_objects.filter(pk__in=rids).values_list("pk", "tenant_id"))

        for rid in rids:
            for pk in sorted(history_pks[rid]):
                message = messages.get(pk)
                if message is None:
                    continue
                if pk in direct[rid]:
                    put(rid, message, "history")
                    continue
                if pk in linked_elsewhere:
                    continue
                tenant_id = request_tenants.get(rid)
                if tenant_id is None:
                    put(rid, message, "history", unconfirmed=True)
                elif message.tenant_id == tenant_id:
                    put(rid, message, "history")
        return result

    @staticmethod
    def _linked_message_pks(pks: set[int]) -> set[int]:
        """pks of TelegramMessage referenced by any model except the history log (cards of any module)."""
        linked: set[int] = set()
        for rel in TelegramMessage._meta.related_objects:
            if rel.related_model is TelegramMessageHistory or not rel.field.concrete:
                continue
            attname = rel.field.attname
            linked.update(
                rel.related_model._base_manager.filter(**{f"{attname}__in": list(pks)})
                .order_by()
                .values_list(attname, flat=True)
            )
        return linked
