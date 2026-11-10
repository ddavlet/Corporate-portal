# Hand-written: Neuron had the top-up message in n8n (personal chat of user 18) — keep it on in the portal.

from django.db import migrations

# (subdomain, recipient user ids); a user is added only while an active member of that tenant
SEED = (("neuron", (18,)),)


def seed(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    TenantMembership = apps.get_model("tenants", "TenantMembership")
    CardTopupNotifyConfig = apps.get_model("cash_desk", "CardTopupNotifyConfig")

    for subdomain, user_ids in SEED:
        tenant = Tenant.objects.filter(subdomain=subdomain).first()
        if tenant is None:
            continue
        member_ids = list(
            TenantMembership.objects.filter(tenant=tenant, user_id__in=user_ids, is_active=True)
            .order_by("user_id")
            .values_list("user_id", flat=True)
        )
        if not member_ids:
            continue
        config, created = CardTopupNotifyConfig.objects.get_or_create(tenant=tenant, defaults={"is_active": True})
        if not created:
            continue  # never override settings already saved by the tenant
        config.recipients.add(*member_ids)


class Migration(migrations.Migration):

    dependencies = [
        ("cash_desk", "0004_card_topup_notifications"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
