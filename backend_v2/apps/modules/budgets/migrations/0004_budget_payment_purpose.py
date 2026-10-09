import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Budgets by payment purpose (назначение платежа) alongside budgets by category.

    Existing rows all have a category and an empty purpose, so they satisfy the new check.
    """

    dependencies = [
        ("budgets", "0003_drop_redundant_tenant_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="budget",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="budgets",
                to="requests.requestcategory",
            ),
        ),
        migrations.AddField(
            model_name="budget",
            name="payment_purpose",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddConstraint(
            model_name="budget",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("category__isnull", False), ("payment_purpose", "")),
                    models.Q(("category__isnull", True), models.Q(("payment_purpose", ""), _negated=True)),
                    _connector="OR",
                ),
                name="budgets_one_dimension",
            ),
        ),
    ]
