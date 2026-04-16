from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bank_expenses", "0013_drop_bankexpense_statement_columns"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="bankexpense",
            name="uniq_bank_expense_doc_date_doc_no_turnover_purpose",
        ),
        migrations.AddConstraint(
            model_name="bankexpense",
            constraint=models.UniqueConstraint(
                fields=["tenant", "doc_date", "doc_no", "debit_turnover", "payment_purpose"],
                name="uniq_bank_expense_tenant_doc_date_doc_no_turnover_purpose",
            ),
        ),
    ]

