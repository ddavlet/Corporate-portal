from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants", "0012_remove_tenantuserrole_step"),
    ]

    operations = [
        migrations.CreateModel(
            name="ClientDebtSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("snapshot_at", models.DateTimeField()),
                ("doc_type", models.CharField(default="client_debt_total", max_length=64)),
                ("organization", models.CharField(blank=True, default="", max_length=200)),
                ("client", models.CharField(blank=True, default="", max_length=255)),
                ("client_id", models.CharField(blank=True, default="", max_length=64)),
                ("debt_sum", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("quantity", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("cert_discount", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_client_debt_snapshots",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="client_debt_snapshots",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "clients_debt_snapshots",
                "ordering": ["-snapshot_at", "-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="clientdebtsnapshot",
            constraint=models.UniqueConstraint(
                fields=("tenant", "snapshot_at", "doc_type", "client_id"),
                name="clients_debt_tenant_date_type_client_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="clientdebtsnapshot",
            index=models.Index(fields=["tenant", "snapshot_at"], name="clients_debt_tenant_date_idx"),
        ),
        migrations.AddIndex(
            model_name="clientdebtsnapshot",
            index=models.Index(fields=["tenant", "client_id"], name="clients_debt_tenant_client_idx"),
        ),
        migrations.AddIndex(
            model_name="clientdebtsnapshot",
            index=models.Index(fields=["tenant", "doc_type"], name="clients_debt_tenant_type_idx"),
        ),
    ]

