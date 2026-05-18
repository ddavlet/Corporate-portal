from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0044_step_payment_chat_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approval",
            name="step_type",
            field=models.CharField(
                choices=[
                    ("serial", "serial"),
                    ("payment", "payment"),
                    ("notification", "notification"),
                ],
                default="serial",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalstepconfig",
            name="step_type",
            field=models.CharField(
                choices=[
                    ("serial", "serial"),
                    ("payment", "payment"),
                    ("notification", "notification"),
                ],
                default="serial",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpurposeexceptionstepconfig",
            name="step_type",
            field=models.CharField(
                choices=[
                    ("serial", "serial"),
                    ("payment", "payment"),
                    ("notification", "notification"),
                ],
                default="serial",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="userrequestapproval",
            name="step_type",
            field=models.CharField(
                choices=[
                    ("serial", "serial"),
                    ("payment", "payment"),
                    ("notification", "notification"),
                ],
                default="serial",
                max_length=16,
            ),
        ),
    ]
