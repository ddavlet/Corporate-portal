import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0008_otpchallenge"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="otpchallenge",
            name="tenant",
            field=models.ForeignKey(
                db_index=False,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="otp_challenges",
                to="tenants.tenant",
            ),
        ),
    ]
