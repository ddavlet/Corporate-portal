from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0005_vendor_name_unique"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                'ALTER TABLE "vendors_directory" '
                'DROP CONSTRAINT IF EXISTS "vendors_directory_tenant_account_number_uniq";'
            ),
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddConstraint(
            model_name="vendor",
            constraint=models.UniqueConstraint(
                condition=(~Q(account_number="") & Q(account_number__isnull=False)),
                fields=("tenant", "account_number"),
                name="vendors_directory_tenant_account_number_uniq",
            ),
        ),
    ]
