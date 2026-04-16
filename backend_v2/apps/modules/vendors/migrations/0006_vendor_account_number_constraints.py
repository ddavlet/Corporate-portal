from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0005_vendor_name_unique"),
    ]

    operations = [
        # CI uses --keepdb, so ensure legacy constraints are removed even if they
        # survived earlier migration history/state drift.
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
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                fields=["tenant", "account_number"],
                condition=~Q(account_number="") & Q(account_number__isnull=False),
                name="vendors_directory_tenant_account_number_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                fields=["tenant", "inn", "account_number"],
                condition=(
                    ~Q(inn="")
                    & Q(inn__isnull=False)
                    & ~Q(account_number="")
                    & Q(account_number__isnull=False)
                ),
                name="vendors_directory_tenant_inn_account_number_uniq",
            ),
        ),
    ]

