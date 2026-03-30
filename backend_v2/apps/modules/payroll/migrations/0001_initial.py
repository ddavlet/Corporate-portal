import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("tenants", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PayrollDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("doc_id", models.TextField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payroll_documents",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_documents",
            },
        ),
        migrations.CreateModel(
            name="PayrollLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("line_no", models.IntegerField()),
                ("employee", models.TextField()),
                ("item", models.TextField()),
                ("description", models.TextField(blank=True, null=True)),
                ("sum", models.DecimalField(decimal_places=2, max_digits=15)),
                ("days_plan", models.IntegerField()),
                ("days_fact", models.IntegerField()),
                ("period_start", models.DateField()),
                ("period_end", models.DateField()),
                ("approval", models.BooleanField(default=False)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="payroll.payrolldocument",
                    ),
                ),
            ],
            options={
                "db_table": "payroll_lines",
            },
        ),
        migrations.AddConstraint(
            model_name="payrolldocument",
            constraint=models.UniqueConstraint(fields=("tenant", "doc_id"), name="uniq_payroll_document_tenant_doc_id"),
        ),
        migrations.AddConstraint(
            model_name="payrollline",
            constraint=models.UniqueConstraint(fields=("document", "line_no"), name="uniq_payroll_line_document_line_no"),
        ),
    ]
