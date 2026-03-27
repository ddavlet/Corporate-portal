from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0003_backfill_tenant_admin_to_admin_role"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql='ALTER TABLE "tenants_tenantmembership" DROP COLUMN IF EXISTS "role";',
                    reverse_sql='ALTER TABLE "tenants_tenantmembership" ADD COLUMN IF NOT EXISTS "role" varchar(30);',
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name="tenantmembership",
                    name="role",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql='DROP TABLE IF EXISTS "tenants_usermodulepermission";',
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.DeleteModel(
                    name="UserModulePermission",
                ),
            ],
        ),
    ]

