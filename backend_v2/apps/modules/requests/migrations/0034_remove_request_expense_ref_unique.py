from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0033_request_expense_ref_target_uniq"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="request",
            name="req_tenant_exp_ref_target_id_uniq",
        ),
    ]
