from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0014_rename_tenants_ten_tenant__4a2a66_idx_tenants_ten_tenant__9191d4_idx"),
    ]

    operations = [
        migrations.AlterField(
            model_name="tenantuserrole",
            name="role",
            field=models.CharField(
                choices=[
                    ("requester", "requester"),
                    ("approver", "approver"),
                    ("admin", "admin"),
                    ("director", "director"),
                    ("cashier", "cashier"),
                    ("accountant", "accountant"),
                    ("investor", "investor"),
                ],
                max_length=30,
            ),
        ),
    ]
