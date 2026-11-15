# Hand-written: branch-only models (make makemigrations runs against main).
# CreateModel only: new empty tables, no locks on existing ones, no backfill.
# Last step: the read-only postgres-mcp role gets SELECT on new tables from ALTER DEFAULT
# PRIVILEGES at CREATE TABLE; the tables with bank personal data are revoked from every reader
# right here, so they are never readable between migrate and the next run of
# scripts/postgres_mcp_create_readonly_role.sql.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


PERSONAL_DATA_TABLES = (
    "payroll_bank_employees",
    "payroll_bank_employee_accounts",
    "payroll_card_batches",
    "payroll_card_payouts",
)


def revoke_personal_data_from_readers(apps, schema_editor):
    """REVOKE SELECT from every role other than the table owner (only default privileges can have
    granted it: the tables are created in this migration). Postgres only; no role names needed."""
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        for table in PERSONAL_DATA_TABLES:
            cursor.execute(
                """
                SELECT DISTINCT p.grantee
                FROM information_schema.table_privileges p
                JOIN pg_tables t ON t.schemaname = p.table_schema AND t.tablename = p.table_name
                WHERE p.table_schema = current_schema()
                  AND p.table_name = %s
                  AND p.privilege_type = 'SELECT'
                  AND p.grantee NOT IN (t.tableowner, 'PUBLIC')
                """,
                [table],
            )
            for (grantee,) in cursor.fetchall():
                cursor.execute(f"REVOKE SELECT ON TABLE {quote(table)} FROM {quote(grantee)}")


class Migration(migrations.Migration):

    dependencies = [
        ("bank_expenses", "0018_remove_bankrevenue_uniq_bank_revenue_tenant_doc_no_doc_date_kredit_turnover_and_more"),
        ("kapitalbank", "0002_account_types"),
        ("payroll", "0007_payrolldocument_comment"),
        ("tenants", "0026_tenant_payroll_payout_mode"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BankPayrollEmployee",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bank_client_id", models.CharField(max_length=32)),
                ("external_id", models.CharField(max_length=32)),
                ("full_name", models.CharField(blank=True, default="", max_length=200)),
                ("masked_card", models.CharField(blank=True, default="", max_length=32)),
                ("branch", models.CharField(blank=True, default="", max_length=5)),
                ("first_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "payroll_bank_employees",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("bank_client_id", "external_id"), name="uniq_payroll_bank_employee_client_external"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BankPayrollEmployeeAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("account_no", models.CharField(max_length=20, unique=True)),
                (
                    "source",
                    models.CharField(choices=[("workers", "GetWorkers1C"), ("zp", "GetZP1C")], max_length=10),
                ),
                ("first_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "bank_employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounts",
                        to="payroll.bankpayrollemployee",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_bank_employee_accounts",
            },
        ),
        migrations.CreateModel(
            name="PayrollCardBatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transit_account", models.CharField(max_length=20)),
                ("transit_branch", models.CharField(blank=True, default="", max_length=5)),
                ("bank_doc_key", models.CharField(max_length=64)),
                ("num", models.CharField(blank=True, default="", max_length=50)),
                ("doc_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("payer_account", models.CharField(blank=True, default="", max_length=20)),
                ("purpose", models.TextField(blank=True, default="")),
                ("period_month", models.DateField()),
                ("tenant_resolved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "bank_expense",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="payroll_card_batches",
                        to="bank_expenses.bankexpense",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payroll_card_batches",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_card_batches",
                "constraints": [
                    models.UniqueConstraint(fields=("transit_account", "bank_doc_key"), name="uniq_payroll_card_batch_doc"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PayrollCardPayout",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transit_account", models.CharField(max_length=20)),
                ("bank_doc_key", models.CharField(max_length=64)),
                ("card_account", models.CharField(max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15)),
                ("paid_on", models.DateField()),
                ("period_month", models.DateField()),
                ("purpose", models.TextField(blank=True, default="")),
                ("name_from_purpose", models.CharField(blank=True, default="", max_length=200)),
                ("employee_assigned_manually", models.BooleanField(default=False)),
                ("attached_at", models.DateTimeField(blank=True, null=True)),
                ("unassigned_alerted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "assigned_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "bank_employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payouts",
                        to="payroll.bankpayrollemployee",
                    ),
                ),
                (
                    "batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payouts",
                        to="payroll.payrollcardbatch",
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="card_payouts",
                        to="payroll.payrolldocument",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="card_payouts",
                        to="payroll.employee",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        blank=True,
                        db_index=False,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payroll_card_payouts",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_card_payouts",
                "indexes": [
                    models.Index(fields=["tenant", "period_month"], name="payroll_card_payout_tenant_pm"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("transit_account", "bank_doc_key"), name="uniq_payroll_card_payout_doc"),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0)), name="payroll_card_payout_amount_positive"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PayrollBankEmployeeLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("decided_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "bank_employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="links",
                        to="payroll.bankpayrollemployee",
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bank_links",
                        to="payroll.employee",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payroll_bank_employee_links",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_bank_employee_links",
                "constraints": [
                    models.UniqueConstraint(fields=("tenant", "bank_employee"), name="uniq_payroll_bank_employee_link"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PayrollExpectedCard",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=15)),
                ("is_manual", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "document",
                    models.ForeignKey(
                        db_index=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="expected_cards",
                        to="payroll.payrolldocument",
                    ),
                ),
                (
                    "employee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="expected_cards",
                        to="payroll.employee",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "payroll_expected_cards",
                "constraints": [
                    models.UniqueConstraint(fields=("document", "employee"), name="uniq_payroll_expected_card"),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gte", 0)), name="payroll_expected_card_amount_non_negative"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PayrollCardSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("card_start_period", models.DateField(blank=True, null=True)),
                ("auto_close_enabled", models.BooleanField(default=False)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payroll_card_settings",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_card_settings",
            },
        ),
        migrations.RunPython(revoke_personal_data_from_readers, migrations.RunPython.noop),
    ]
