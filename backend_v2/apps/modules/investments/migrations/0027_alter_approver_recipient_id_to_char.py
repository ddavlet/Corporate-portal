from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("investments", "0026_remove_old_chat_id_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="investmentreturnapproval",
            name="approver_recipient_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name="projectinvestmentapproval",
            name="approver_recipient_id",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
