from django.db import migrations


def forwards(apps, schema_editor):
    TenantModuleConfig = apps.get_model("tenants", "TenantModuleConfig")
    tenant_ids = (
        TenantModuleConfig.objects.filter(
            module_key__in=["requests", "cash", "bank"],
            is_enabled=True,
        )
        .values_list("tenant_id", flat=True)
        .distinct()
    )
    for tid in tenant_ids:
        TenantModuleConfig.objects.get_or_create(
            tenant_id=tid,
            module_key="vendors",
            defaults={"is_enabled": True},
        )


def backwards(apps, schema_editor):
    TenantModuleConfig = apps.get_model("tenants", "TenantModuleConfig")
    TenantModuleConfig.objects.filter(module_key="vendors").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0001_initial"),
        ("tenants", "0005_tenant_telegram_otp_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
