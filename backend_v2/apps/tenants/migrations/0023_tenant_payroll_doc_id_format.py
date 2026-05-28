from django.db import migrations, models


def copy_cash_format_to_payroll(apps, schema_editor):
    Tenant = apps.get_model("tenants", "Tenant")
    for tenant in Tenant.objects.all().iterator():
        tenant.payroll_doc_id_prefix = tenant.cash_expense_external_id_prefix
        tenant.payroll_doc_id_digit_width = tenant.cash_expense_external_id_digit_width
        tenant.save(
            update_fields=["payroll_doc_id_prefix", "payroll_doc_id_digit_width"],
        )


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0022_tenant_mcp_enabled"),
    ]

    operations = [
        migrations.AddField(
            model_name="tenant",
            name="payroll_doc_id_prefix",
            field=models.CharField(default="1-", max_length=32),
        ),
        migrations.AddField(
            model_name="tenant",
            name="payroll_doc_id_digit_width",
            field=models.PositiveSmallIntegerField(default=9),
        ),
        migrations.RunPython(copy_cash_format_to_payroll, migrations.RunPython.noop),
    ]
