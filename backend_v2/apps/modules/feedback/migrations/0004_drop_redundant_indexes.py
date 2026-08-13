import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("feedback", "0003_alter_portalfeedback_assignee"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="portalfeedback",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="portal_feedbacks",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="portalfeedback",
            name="assignee",
            field=models.ForeignKey(
                blank=True,
                db_index=False,
                limit_choices_to={"is_staff": True},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_portal_feedbacks",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
