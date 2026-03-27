from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantUserRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[
                    ("requester", "requester"),
                    ("approver", "approver"),
                    ("admin", "admin"),
                    ("director", "director"),
                    ("cashier", "cashier"),
                    ("accountant", "accountant"),
                ], max_length=30)),
                ("step", models.IntegerField()),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_user_roles", to="tenants.tenant")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_roles", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "unique_together": {("tenant", "user", "role")},
            },
        ),
    ]

