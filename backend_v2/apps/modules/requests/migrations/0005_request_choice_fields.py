from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0004_requester_fk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="currency",
            field=models.CharField(
                choices=[("UZS", "UZS"), ("USD", "USD"), ("EUR", "EUR"), ("RUB", "RUB")],
                default="UZS",
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="request",
            name="payment_type",
            field=models.CharField(
                choices=[
                    ("Наличные", "Наличные"),
                    ("Перечисление", "Перечисление"),
                    ("Пополнение", "Пополнение"),
                    ("Платежная карта", "Платежная карта"),
                ],
                default="Наличные",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="request",
            name="urgency",
            field=models.CharField(
                choices=[("Низкая", "Низкая"), ("Обычная", "Обычная"), ("Высокая", "Высокая")],
                default="Обычная",
                max_length=50,
            ),
        ),
    ]

