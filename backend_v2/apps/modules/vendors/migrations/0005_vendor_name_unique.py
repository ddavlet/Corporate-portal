from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0004_fix_vendor_constraints_state"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_inn_transfer_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_inn_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_name_kind_cash_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_name_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                condition=~Q(name=""),
                fields=("tenant", "name"),
                name="vendors_directory_tenant_name_uniq",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="vendor",
                    name="vendors_directory_tenant_inn_uniq",
                ),
                migrations.RemoveConstraint(
                    model_name="vendor",
                    name="vendors_directory_tenant_name_kind_cash_uniq",
                ),
            ],
        ),
    ]
