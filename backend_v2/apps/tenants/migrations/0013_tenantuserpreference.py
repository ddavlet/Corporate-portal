from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0012_remove_tenantuserrole_step"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TenantUserPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=120)),
                ("value", models.JSONField(default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="user_preferences", to="tenants.tenant"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tenant_preferences", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "unique_together": {("tenant", "user", "key")},
            },
        ),
        migrations.AddIndex(
            model_name="tenantuserpreference",
            index=models.Index(fields=["tenant", "user", "key"], name="tenants_ten_tenant__4a2a66_idx"),
        ),
    ]
