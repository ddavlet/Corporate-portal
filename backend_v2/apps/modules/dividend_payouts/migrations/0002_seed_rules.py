"""Initial dividend payout rules (moved from the n8n «New Payed Request» workflow) and the Qulay purpose split.

Idempotent: rules and purposes are get-or-created; nothing is deleted. Reverse is a no-op.
"""

from django.db import migrations

PRINCIPAL = "тело_инвестиций"
DIVIDEND = "дивиденды"
INVESTOR = "инвестор"
PARTNER = "партнер"

FOUNDER_PURPOSE = "Дивиденды учредителю"
PARTNER_PURPOSE = "Дивиденды партнерам"
OLD_QULAY_PURPOSE = "Дивиденды"

LEMON_RULES = (
    (FOUNDER_PURPOSE, PRINCIPAL, INVESTOR),
    (PARTNER_PURPOSE, PRINCIPAL, PARTNER),
)

# subdomain -> ((payment_purpose, return_type, recipient), ...)
SEED_RULES = {
    "lemonfit": LEMON_RULES,
    "lemonaqua": LEMON_RULES,
    "lemonhavo": LEMON_RULES,
    "lemonnew": LEMON_RULES,
    "neuron": (("Дивиденды", PRINCIPAL, INVESTOR),),
    "qulay": (
        (FOUNDER_PURPOSE, DIVIDEND, INVESTOR),
        (PARTNER_PURPOSE, DIVIDEND, PARTNER),
    ),
    "kp": (("Дивиденды", DIVIDEND, INVESTOR),),
}

QULAY_SUBDOMAIN = "qulay"
QULAY_NEW_PURPOSES = (FOUNDER_PURPOSE, PARTNER_PURPOSE)


def seed_rules(apps) -> None:
    Tenant = apps.get_model("tenants", "Tenant")
    DividendPayoutRule = apps.get_model("dividend_payouts", "DividendPayoutRule")

    for subdomain, rules in SEED_RULES.items():
        tenant = Tenant.objects.filter(subdomain=subdomain).first()
        if tenant is None:
            continue
        for purpose, return_type, recipient in rules:
            # Case-insensitive lookup matches the (tenant, lower(payment_purpose)) unique constraint.
            if DividendPayoutRule.objects.filter(tenant=tenant, payment_purpose__iexact=purpose).exists():
                continue
            DividendPayoutRule.objects.create(
                tenant=tenant,
                payment_purpose=purpose,
                return_type=return_type,
                recipient=recipient,
                is_active=True,
            )


def split_qulay_dividend_purpose(apps) -> None:
    """Qulay: every active «Дивиденды» purpose gets «… учредителю» / «… партнерам» siblings and is deactivated."""
    Tenant = apps.get_model("tenants", "Tenant")
    RequestPaymentPurposeConfig = apps.get_model("requests", "RequestPaymentPurposeConfig")

    tenant = Tenant.objects.filter(subdomain=QULAY_SUBDOMAIN).first()
    if tenant is None:
        return
    old_purposes = RequestPaymentPurposeConfig.objects.filter(
        payment_type_config__config__tenant=tenant, name=OLD_QULAY_PURPOSE, is_active=True
    )
    for old in old_purposes:
        for name in QULAY_NEW_PURPOSES:
            purpose, created = RequestPaymentPurposeConfig.objects.get_or_create(
                payment_type_config_id=old.payment_type_config_id,
                name=name,
                defaults={"category": old.category, "is_active": True},
            )
            if not created and not purpose.is_active:
                purpose.is_active = True
                purpose.save(update_fields=["is_active"])
        old.is_active = False
        old.save(update_fields=["is_active"])


def seed(apps, schema_editor):
    seed_rules(apps)
    split_qulay_dividend_purpose(apps)


class Migration(migrations.Migration):

    dependencies = [
        ("dividend_payouts", "0001_initial"),
        ("requests", "0067_request_invest_payment_types"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
