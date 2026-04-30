from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budgets", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="budget",
            name="limit_amount",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=18,
                validators=[MinValueValidator(Decimal("0.01"))],
            ),
        ),
    ]
