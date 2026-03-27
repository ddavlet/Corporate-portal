from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0005_tenant_telegram_otp_fields"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Note",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "target_type",
                    models.CharField(
                        choices=[("request", "request"), ("cash", "cash"), ("bank", "bank")],
                        max_length=20,
                    ),
                ),
                ("target_id", models.BigIntegerField()),
                ("message", models.TextField()),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[("pending", "pending"), ("sent", "sent"), ("failed", "failed")],
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
                        related_name="created_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "recipient_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="received_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notes",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "notes",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(fields=["tenant", "target_type", "target_id"], name="notes_tenant_target_idx"),
        ),
        migrations.AddIndex(
            model_name="note",
            index=models.Index(fields=["recipient_user", "created_at"], name="notes_recipient_created_idx"),
        ),
    ]
