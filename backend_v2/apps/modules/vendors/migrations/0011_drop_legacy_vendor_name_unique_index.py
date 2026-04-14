from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0010_drop_legacy_vendor_inn_unique_index"),
    ]

    operations = [
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS "vendors_directory_tenant_name_uniq";',
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
