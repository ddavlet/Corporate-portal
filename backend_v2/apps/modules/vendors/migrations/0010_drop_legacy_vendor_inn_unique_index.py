from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0009_drop_legacy_vendor_inn_unique_constraint"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_inn_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "vendors_directory_tenant_inn_uniq";',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
