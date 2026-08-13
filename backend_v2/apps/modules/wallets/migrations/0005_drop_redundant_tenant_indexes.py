import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0004_wallet_is_visible_in_cash_section"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="bankaccount",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bank_accounts_wallets",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="wallet",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wallets",
                        to="tenants.tenant",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(
                    ("wallets", "BankAccount", "tenant"),
                    ("wallets", "Wallet", "tenant"),
                ),
            ],
        ),
    ]
