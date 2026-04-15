from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants", "0014_rename_tenants_ten_tenant__4a2a66_idx_tenants_ten_tenant__9191d4_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestReturn",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("sum", models.DecimalField(decimal_places=2, max_digits=18)),
                ("comment", models.TextField(blank=True, default="")),
                ("confirmed", models.BooleanField(default=False)),
                ("currency", models.CharField(default="USD", max_length=3)),
                (
                    "type",
                    models.CharField(
                        choices=[
                            ("дивиденды", "Дивиденды"),
                            ("проценты", "Проценты"),
                            ("доля_прибыли", "Доля прибыли"),
                            ("тело_инвестиций", "Тело инвестиций"),
                        ],
                        max_length=25,
                    ),
                ),
                (
                    "recipient",
                    models.CharField(
                        choices=[
                            ("инвестор", "Инвестор"),
                            ("партнер", "Партнер"),
                        ],
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_invest_returns",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="invest_returns",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "invest_returns",
                "ordering": ["-date", "-created_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="investreturn",
            index=models.Index(fields=["tenant", "date"], name="invest_returns_tenant_date_idx"),
        ),
        migrations.AddIndex(
            model_name="investreturn",
            index=models.Index(fields=["tenant", "confirmed"], name="invest_returns_tenant_confirmed_idx"),
        ),
    ]
