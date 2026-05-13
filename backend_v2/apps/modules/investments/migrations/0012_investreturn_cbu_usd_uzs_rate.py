from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0011_investment_step_type_and_payment_chat"),
    ]

    operations = [
        migrations.AddField(
            model_name="investreturn",
            name="cbu_usd_uzs_rate",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Курс ЦБ РУз: сум за 1 USD на дату создания заявки (фиксируется при создании).",
                max_digits=20,
                null=True,
            ),
        ),
    ]
