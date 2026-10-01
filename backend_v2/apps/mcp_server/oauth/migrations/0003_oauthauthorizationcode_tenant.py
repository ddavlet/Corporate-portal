import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mcp_oauth", "0002_alter_oauthauthorizationcode_state_code_challenge"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="oauthauthorizationcode",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="mcp_oauth_codes",
                to="tenants.tenant",
            ),
        ),
    ]
