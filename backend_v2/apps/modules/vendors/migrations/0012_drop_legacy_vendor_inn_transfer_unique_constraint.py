from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0011_drop_legacy_vendor_name_unique_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_inn_transfer_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Some historical Postgres states can leave a unique index behind even if the
        # constraint is removed or renamed.
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "vendors_directory_tenant_inn_transfer_uniq";',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

