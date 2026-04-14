from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0008_vendor_inn_account_number_unique"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "vendors_directory" '
                        'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_inn_uniq";'
                    ),
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[],
        ),
    ]
