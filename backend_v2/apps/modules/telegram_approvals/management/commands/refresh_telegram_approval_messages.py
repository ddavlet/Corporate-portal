from django.core.management.base import BaseCommand

from apps.modules.requests.models import Request
from apps.modules.telegram_approvals.services import refresh_request_messages


class Command(BaseCommand):
    help = (
        "Точечно обновить (edit) Telegram-карточки согласований по заявкам: "
        "текст и кнопки в соответствии с текущим состоянием в БД. "
        "На production: make refresh-approval-messages REQUEST_IDS='…'."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "request_ids",
            nargs="+",
            type=int,
            help="ID заявок (Request.pk), один или несколько",
        )

    def handle(self, *args, **options):
        ids = list(dict.fromkeys(options["request_ids"]))
        if not ids:
            return

        total = 0
        for pk in ids:
            try:
                request_obj = Request.objects.get(pk=pk)
            except Request.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Request id={pk}: не найдена"))
                continue
            n = refresh_request_messages(request_obj=request_obj)
            total += n
            self.stdout.write(f"Request id={pk}: обновлено карточек: {n}")

        self.stdout.write(self.style.SUCCESS(f"Всего успешных правок (суммарно): {total}"))
