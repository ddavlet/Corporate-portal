from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("vendors", "0003_vendor_inn_unique_when_present"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name="vendor",
                    name="vendors_directory_tenant_inn_transfer_uniq",
                ),
            ],
        ),
    ]
