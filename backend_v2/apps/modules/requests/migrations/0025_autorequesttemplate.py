from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("vendors", "0002_enable_vendors_for_requests_tenants"),
        ("requests", "0024_requestapprovalconfig_integration_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AutoRequestTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                ("name", models.CharField(default="", max_length=150)),
                (
                    "payment_type",
                    models.CharField(
                        choices=[
                            ("Наличные", "Наличные"),
                            ("Перечисление", "Перечисление"),
                            ("Пополнение", "Пополнение"),
                            ("Платежная карта", "Платежная карта"),
                        ],
                        max_length=50,
                    ),
                ),
                ("day_of_month", models.IntegerField(default=1)),
                ("title_template", models.CharField(default="", max_length=200)),
                ("description_template", models.TextField(default="")),
                ("company_payer", models.CharField(blank=True, default="", max_length=100)),
                ("amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                (
                    "currency",
                    models.CharField(
                        choices=[("UZS", "UZS"), ("USD", "USD"), ("EUR", "EUR"), ("RUB", "RUB")],
                        default="UZS",
                        max_length=10,
                    ),
                ),
                (
                    "urgency",
                    models.CharField(
                        choices=[("Низко", "Низко"), ("Обычно", "Обычно"), ("Срочно", "Срочно")],
                        default="Обычно",
                        max_length=50,
                    ),
                ),
                ("payment_purpose", models.CharField(blank=True, default="", max_length=200)),
                ("last_run_month", models.DateField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "requester",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="auto_request_templates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="auto_request_templates",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_auto_request_templates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "vendor_ref",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="auto_request_templates",
                        to="vendors.vendor",
                    ),
                ),
            ],
            options={
                "db_table": "auto_request_templates",
            },
        ),
        migrations.AddIndex(
            model_name="autorequesttemplate",
            index=models.Index(fields=["tenant", "is_enabled"], name="auto_req_tenant_enabled_idx"),
        ),
        migrations.AddIndex(
            model_name="autorequesttemplate",
            index=models.Index(fields=["tenant", "payment_type"], name="auto_req_tenant_payment_idx"),
        ),
        migrations.AddIndex(
            model_name="autorequesttemplate",
            index=models.Index(fields=["tenant", "last_run_month"], name="auto_req_tenant_run_month_idx"),
        ),
    ]
