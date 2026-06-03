from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0053_request_payment_type_payroll"),
        ("telegram_approvals", "0002_telegram_message"),
    ]

    operations = [
        migrations.AddField(
            model_name="approval",
            name="telegram_message",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="request_approval",
                to="telegram_approvals.telegrammessage",
            ),
        ),
    ]
