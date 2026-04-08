from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0006_vendor_account_number_unique"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_name_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="vendor",
                    name="vendors_directory_tenant_name_uniq",
                ),
            ],
        ),
    ]
