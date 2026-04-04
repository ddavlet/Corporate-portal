import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0011_tenantintegrationconfig_portal_feedback"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PortalFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("error", "error"), ("improvement", "improvement")], max_length=20)),
                ("body", models.TextField()),
                ("page_path", models.CharField(blank=True, default="", max_length=500)),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[
                            ("pending", "pending"),
                            ("sent", "sent"),
                            ("failed", "failed"),
                            ("skipped", "skipped"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("delivery_error", models.TextField(blank=True, default="")),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="portal_feedbacks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="portal_feedbacks",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "portal_feedbacks",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="portalfeedback",
            index=models.Index(fields=["tenant", "created_at"], name="portal_fb_tenant_created_idx"),
        ),
    ]
