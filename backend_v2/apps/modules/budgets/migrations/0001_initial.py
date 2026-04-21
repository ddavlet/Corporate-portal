from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("requests", "0037_requestattachment"),
        ("tenants", "0015_tenantuserrole_add_investor_role"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Budget",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                (
                    "period_type",
                    models.CharField(
                        max_length=20,
                        choices=[
                            ("monthly", "Ежемесячно"),
                            ("quarterly", "Ежеквартально"),
                            ("yearly", "Ежегодно"),
                        ],
                    ),
                ),
                ("limit_amount", models.DecimalField(max_digits=18, decimal_places=2)),
                (
                    "currency",
                    models.CharField(
                        max_length=3,
                        default="UZS",
                        choices=[
                            ("UZS", "UZS"),
                            ("USD", "USD"),
                            ("EUR", "EUR"),
                            ("RUB", "RUB"),
                        ],
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="budgets",
                        to="requests.requestcategory",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_budgets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="budgets",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"db_table": "budgets"},
        ),
        migrations.AddConstraint(
            model_name="budget",
            constraint=models.UniqueConstraint(
                fields=["tenant", "name"],
                name="budgets_tenant_name_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="budget",
            index=models.Index(fields=["tenant", "is_active"], name="budgets_tenant_active_idx"),
        ),
        migrations.AddIndex(
            model_name="budget",
            index=models.Index(fields=["tenant", "category"], name="budgets_tenant_category_idx"),
        ),
    ]
