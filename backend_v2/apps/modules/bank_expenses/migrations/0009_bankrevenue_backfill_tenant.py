from django.db import migrations


def forwards(apps, schema_editor):
    BankRevenue = apps.get_model("bank_expenses", "BankRevenue")
    Tenant = apps.get_model("tenants", "Tenant")
    missing = []
    for row in BankRevenue.objects.iterator():
        tenant = Tenant.objects.filter(subdomain=row.tenant_subdomain).first()
        if tenant is None:
            missing.append((row.pk, row.tenant_subdomain))
        else:
            BankRevenue.objects.filter(pk=row.pk).update(tenant_id=tenant.pk)
    if missing:
        sample = ", ".join(f"id={pk} subdomain={sub!r}" for pk, sub in missing[:50])
        suffix = " ..." if len(missing) > 50 else ""
        raise RuntimeError(
            f"BankRevenue backfill: no Tenant for tenant_subdomain ({len(missing)} rows): {sample}{suffix}"
        )


def backwards(apps, schema_editor):
    BankRevenue = apps.get_model("bank_expenses", "BankRevenue")
    BankRevenue.objects.update(tenant_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0008_bankrevenue_tenant_nullable"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
