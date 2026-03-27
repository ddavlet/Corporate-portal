from django.db import migrations


def forwards(apps, schema_editor):
    TenantMembership = apps.get_model("tenants", "TenantMembership")
    TenantUserRole = apps.get_model("tenants", "TenantUserRole")
    connection = schema_editor.connection

    # Be defensive with drifted DBs: skip backfill if legacy `role` column
    # was already removed earlier.
    membership_table = TenantMembership._meta.db_table
    with connection.cursor() as cursor:
        table_names = connection.introspection.table_names(cursor)
        if membership_table not in table_names:
            return
        description = connection.introspection.get_table_description(cursor, membership_table)
        columns = {c.name for c in description}
    if "role" not in columns:
        return

    # Backfill legacy membership.role="tenant_admin" into TenantUserRole(role="admin").
    # We use step=100 to match existing seed conventions.
    admin_memberships = TenantMembership.objects.filter(role="tenant_admin", is_active=True)
    for m in admin_memberships.iterator():
        TenantUserRole.objects.get_or_create(
            tenant_id=m.tenant_id,
            user_id=m.user_id,
            role="admin",
            defaults={"step": 100},
        )


def backwards(apps, schema_editor):
    # Best-effort rollback: do not delete admin roles because they may be legitimate
    # (created independently). Leaving data is safer than destructive reversal.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0002_tenantuserrole"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

