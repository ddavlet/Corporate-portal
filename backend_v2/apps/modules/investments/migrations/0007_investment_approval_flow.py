from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tenants", "0007_remove_extra_tenant_integration_fields"),
        ("investments", "0006_investpayoutschedulesharelink"),
    ]

    operations = [
        migrations.CreateModel(
            name="InvestmentApprovalConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_approval_config",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"db_table": "investment_approval_config"},
        ),
        migrations.CreateModel(
            name="InvestmentApprovalConfigStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step", models.PositiveIntegerField()),
                ("is_enabled", models.BooleanField(default=True)),
                (
                    "config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="investments.investmentapprovalconfig",
                    ),
                ),
            ],
            options={
                "db_table": "investment_approval_config_steps",
                "ordering": ["step", "id"],
                "unique_together": {("config", "step")},
            },
        ),
        migrations.CreateModel(
            name="InvestmentApprovalConfigStepApprover",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "approver_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_step_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "step",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="step_approvers",
                        to="investments.investmentapprovalconfigstep",
                    ),
                ),
            ],
            options={
                "db_table": "investment_approval_config_step_approvers",
                "unique_together": {("step", "approver_user")},
            },
        ),
        migrations.AddField(
            model_name="investmentapprovalconfigstep",
            name="approver_users",
            field=models.ManyToManyField(
                related_name="investment_approval_steps",
                through="investments.InvestmentApprovalConfigStepApprover",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="InvestmentReturnApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step", models.PositiveIntegerField()),
                (
                    "decision",
                    models.CharField(
                        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("decision_comment", models.TextField(blank=True, default="")),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("approver_tg_id", models.BigIntegerField(blank=True, null=True)),
                ("approver_tg_from_id", models.BigIntegerField(blank=True, null=True)),
                ("message_id", models.BigIntegerField(blank=True, null=True)),
                ("message_sent", models.BooleanField(default=False)),
                ("message_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approver_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="investment_return_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "invest_return",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approvals",
                        to="investments.investreturn",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_return_approvals",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "investment_return_approvals",
                "ordering": ["step", "id"],
                "unique_together": {("invest_return", "step", "approver_user")},
            },
        ),
        migrations.AddIndex(
            model_name="investmentapprovalconfigstep",
            index=models.Index(fields=["config", "step"], name="invcfg_step_cfg_step_idx"),
        ),
        migrations.AddIndex(
            model_name="investmentapprovalconfigstepapprover",
            index=models.Index(fields=["step", "approver_user"], name="invcfg_step_appr_idx"),
        ),
        migrations.AddIndex(
            model_name="investmentreturnapproval",
            index=models.Index(fields=["tenant", "invest_return"], name="invrapp_tenant_ret_idx"),
        ),
        migrations.AddIndex(
            model_name="investmentreturnapproval",
            index=models.Index(fields=["tenant", "decision"], name="invrapp_tenant_dec_idx"),
        ),
        migrations.AddIndex(
            model_name="investmentreturnapproval",
            index=models.Index(fields=["approver_tg_id"], name="invrapp_tg_id_idx"),
        ),
        migrations.AddIndex(
            model_name="investmentreturnapproval",
            index=models.Index(fields=["message_id"], name="invrapp_msg_id_idx"),
        ),
    ]
