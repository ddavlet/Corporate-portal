# Generated migration for Notification model and investment approval refactoring

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("telegram_approvals", "0002_telegram_message"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("draft", "Draft request notification"), ("portal_feedback", "Portal feedback delivery")], max_length=20)),
                ("object_id", models.PositiveIntegerField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("content_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="contenttypes.contenttype")),
                ("telegram_message", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="notification", to="telegram_approvals.telegrammessage")),
                ("tenant", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to="tenants.tenant")),
            ],
            options={
                "db_table": "notifications",
                "indexes": [
                    models.Index(fields=["tenant", "kind", "created_at"], name="notif_tenant_kind_created_idx"),
                    models.Index(fields=["content_type", "object_id"], name="notif_source_idx"),
                ],
            },
        ),
    ]
