import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("notes", "0001_initial"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="note",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notes",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="note",
                    name="recipient_user",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="received_notes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(
                    ("notes", "Note", "tenant"),
                    ("notes", "Note", "recipient_user"),
                ),
            ],
        ),
    ]
