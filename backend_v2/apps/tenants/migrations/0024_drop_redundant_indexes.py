import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0023_tenant_payroll_doc_id_format"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveIndex(model_name="tenantuserpreference", name="tenants_ten_tenant__9191d4_idx"),
        migrations.AlterField(
            model_name="tenantmembership",
            name="user",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="tenantmoduleconfig",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="module_configs",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="tenantuserrole",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="tenant_user_roles",
                to="tenants.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="tenantuserpreference",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="user_preferences",
                to="tenants.tenant",
            ),
        ),
    ]
