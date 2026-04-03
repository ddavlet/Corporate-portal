# One-time: удалить неиспользуемые RequestCategory для тенанта lemonfit
# (нет в Request.category и нет в RequestPaymentPurposeConfig.category).

from django.db import migrations


def prune_unused_categories_lemonfit(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    RequestCategory = apps.get_model("requests", "RequestCategory")
    Request = apps.get_model("requests", "Request")
    RequestPaymentPurposeConfig = apps.get_model("requests", "RequestPaymentPurposeConfig")

    tenant = Tenant.objects.filter(subdomain="lemonfit").first()
    if not tenant:
        return

    used = set()
    for raw in Request.objects.filter(tenant_id=tenant.pk).values_list("category", flat=True):
        name = (raw or "").strip()
        if name:
            used.add(name)

    for raw in RequestPaymentPurposeConfig.objects.filter(
        payment_type_config__config__tenant_id=tenant.pk
    ).values_list("category", flat=True):
        name = (raw or "").strip()
        if name:
            used.add(name)

    RequestCategory.objects.filter(tenant_id=tenant.pk).exclude(name__in=used).delete()


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0027_autorequesttemplate_billing_month_mode"),
    ]

    operations = [
        migrations.RunPython(prune_unused_categories_lemonfit, noop),
    ]
