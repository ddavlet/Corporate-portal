from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0012_remove_tenantuserrole_step"),
        ("requests", "0036_requestapprovalpaymenttypeconfig_request_not_required_rules"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RequestAttachment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file_path", models.TextField()),
                ("file_name", models.CharField(max_length=255)),
                ("content_type", models.CharField(blank=True, default="", max_length=255)),
                ("size_bytes", models.BigIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="request_attachments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="requests.request",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_attachments",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "request_attachments",
            },
        ),
        migrations.AddIndex(
            model_name="requestattachment",
            index=models.Index(fields=["tenant", "request"], name="req_att_tenant_req_idx"),
        ),
        migrations.AddIndex(
            model_name="requestattachment",
            index=models.Index(fields=["request", "created_at"], name="req_att_req_created_idx"),
        ),
    ]
