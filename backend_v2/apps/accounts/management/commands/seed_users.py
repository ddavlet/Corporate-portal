from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.tenants.models import Tenant, TenantMembership, TenantUserRole


SEED_ROWS = [
    {
        "name": "Дильшод Давлетьяров",
        "role": "admin",
        "telegram_chat_id": 1387986,
        "step": 100,
        "telegram_from_id": 1387986,
    },
    {
        "name": "Руслан Бухгалтер",
        "role": "accountant",
        "telegram_chat_id": 5333994857,
        "step": 100,
        "telegram_from_id": 5333994857,
    },
    {
        "name": "Наталья Сумина",
        "role": "cashier",
        "telegram_chat_id": 208686785,
        "step": 100,
        "telegram_from_id": 208686785,
    },
    {
        "name": "Наталья Сумина",
        "role": "approver",
        "telegram_chat_id": 208686785,
        "step": 1,
        "telegram_from_id": 208686785,
    },
    {
        "name": "Руслан Элманов",
        "role": "approver",
        "telegram_chat_id": 2715877,
        "step": 2,
        "telegram_from_id": 2715877,
    },
    {
        "name": "Давлетьяров Сардор",
        "role": "approver",
        "telegram_chat_id": 291875946,
        "step": 4,
        "telegram_from_id": 291875946,
    },
    {
        "name": "Бухгалтер Гузаль",
        "role": "approver",
        "telegram_chat_id": 5239578766,
        "step": 3,
        "telegram_from_id": 5239578766,
    },
    {
        "name": "Бухгалтер Гузаль",
        "role": "accountant",
        "telegram_chat_id": 5239578766,
        "step": 100,
        "telegram_from_id": 5239578766,
    },
]


class Command(BaseCommand):
    help = "Populate users and tenant roles from predefined seed rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant",
            dest="tenant_subdomain",
            required=True,
            help="Tenant subdomain where roles/memberships will be created (e.g. lemonfit).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        tenant_subdomain = options["tenant_subdomain"].strip().lower()
        tenant = Tenant.objects.filter(subdomain=tenant_subdomain).first()
        if not tenant:
            raise CommandError(f"Tenant '{tenant_subdomain}' not found.")

        User = get_user_model()

        users_created = 0
        roles_upserted = 0
        memberships_upserted = 0

        for row in SEED_ROWS:
            telegram_from_id = row["telegram_from_id"]
            username = f"tg_{telegram_from_id}"

            user = User.objects.filter(telegram_from_id=telegram_from_id).first()
            if not user:
                user = User(username=username)
                user.set_unusable_password()
                users_created += 1

            # Fill requested fields + minimal required auth field.
            user.first_name = row["name"]
            user.full_name = row["name"]
            user.last_name = ""
            user.telegram_chat_id = row["telegram_chat_id"]
            user.telegram_from_id = row["telegram_from_id"]
            user.is_active = True
            user.save()

            TenantMembership.objects.update_or_create(
                tenant=tenant,
                user=user,
                defaults={
                    "is_active": True,
                },
            )
            memberships_upserted += 1

            TenantUserRole.objects.update_or_create(
                tenant=tenant,
                user=user,
                role=row["role"],
                defaults={"step": row["step"]},
            )
            roles_upserted += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Users created: {users_created}, memberships upserted: {memberships_upserted}, roles upserted: {roles_upserted}."
        ))

