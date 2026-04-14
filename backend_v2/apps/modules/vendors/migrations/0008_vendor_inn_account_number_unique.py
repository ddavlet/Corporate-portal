from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0007_drop_vendor_name_unique"),
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
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_inn_account_number_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                condition=(
                    ~Q(inn="")
                    & Q(inn__isnull=False)
                    & ~Q(account_number="")
                    & Q(account_number__isnull=False)
                ),
                fields=("tenant", "inn", "account_number"),
                name="vendors_directory_tenant_inn_account_number_uniq",
            ),
        ),
    ]
