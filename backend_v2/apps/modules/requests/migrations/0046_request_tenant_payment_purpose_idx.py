from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0045_approval_step_type_notification"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="request",
            index=models.Index(
                fields=["tenant", "payment_type", "payment_purpose"],
                name="req_tenant_pt_purpose_idx",
                condition=models.Q(payment_purpose__gt=""),
            ),
        ),
    ]
