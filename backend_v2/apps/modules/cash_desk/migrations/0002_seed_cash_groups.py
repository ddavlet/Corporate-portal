from django.db import migrations

# (subdomain, chat_id, name used only when the group does not exist yet)
SEED = (
    ("lemonfit", "-1004412904548", "Касса LemonFit One"),
    ("lemonaqua", "-5321395304", "Касса AQUA"),
    ("lemonhavo", "-5456539546", "Касса HAVO"),
    ("lemonnew", "-5457282029", "Касса NEW"),
    ("neuron", "-1002710729577", "NM - касса"),
    ("qulay", "-4841328641", "QULAY BOX buxgalteriyasi"),
)


def seed(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    TenantTelegramChat = apps.get_model("telegram_approvals", "TenantTelegramChat")
    CashDeskConfig = apps.get_model("cash_desk", "CashDeskConfig")

    for subdomain, chat_id, name in SEED:
        tenant = Tenant.objects.filter(subdomain=subdomain).first()
        if tenant is None:
            continue
        chat, _ = TenantTelegramChat.objects.get_or_create(
            tenant=tenant, chat_id=chat_id, defaults={"name": name, "is_active": True}
        )
        CashDeskConfig.objects.get_or_create(tenant=tenant, defaults={"is_active": False, "telegram_chat": chat})


class Migration(migrations.Migration):

    dependencies = [
        ("cash_desk", "0001_initial"),
        ("telegram_approvals", "0006_drop_redundant_indexes"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
