from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("investments", "0017_investment_approval_config_recipient"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectinvestment",
            name="confirmed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="projectinvestment",
            index=models.Index(fields=["tenant", "confirmed"], name="invproj_tenant_conf_idx"),
        ),
        migrations.CreateModel(
            name="InvestmentProjectApprovalConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_enabled", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_project_approval_config",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={"db_table": "investment_project_approval_config"},
        ),
        migrations.CreateModel(
            name="InvestmentProjectApprovalConfigStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step", models.PositiveIntegerField()),
                (
                    "step_type",
                    models.CharField(
                        choices=[
                            ("serial", "serial"),
                            ("confirmation", "confirmation"),
                            ("notification", "notification"),
                        ],
                        default="serial",
                        max_length=16,
                    ),
                ),
                ("is_enabled", models.BooleanField(default=True)),
                ("payment_chat_id", models.BigIntegerField(blank=True, null=True)),
                (
                    "config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="investments.investmentprojectapprovalconfig",
                    ),
                ),
            ],
            options={
                "db_table": "investment_project_approval_config_steps",
                "ordering": ["step", "id"],
                "unique_together": {("config", "step")},
            },
        ),
        migrations.CreateModel(
            name="InvestmentProjectApprovalConfigStepApprover",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "approver_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="investment_project_step_assignments",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "step",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="step_approvers",
                        to="investments.investmentprojectapprovalconfigstep",
                    ),
                ),
            ],
            options={
                "db_table": "investment_project_approval_config_step_approvers",
                "unique_together": {("step", "approver_user")},
            },
        ),
        migrations.AddField(
            model_name="investmentprojectapprovalconfigstep",
            name="approver_users",
            field=models.ManyToManyField(
                related_name="investment_project_approval_steps",
                through="investments.InvestmentProjectApprovalConfigStepApprover",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="ProjectInvestmentApproval",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step", models.PositiveIntegerField()),
                (
                    "step_type",
                    models.CharField(
                        choices=[
                            ("serial", "serial"),
                            ("confirmation", "confirmation"),
                            ("notification", "notification"),
                        ],
                        default="serial",
                        max_length=16,
                    ),
                ),
                ("approver_recipient_id", models.BigIntegerField(blank=True, null=True)),
                ("approver_external_user_id", models.BigIntegerField(blank=True, null=True)),
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
                ("gateway_message_id", models.BigIntegerField(blank=True, null=True)),
                ("message_sent", models.BooleanField(default=False)),
                ("message_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approver_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="project_investment_approvals_made",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project_investment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approvals",
                        to="investments.projectinvestment",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_investment_approvals",
                        to="tenants.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "project_investment_approvals",
                "ordering": ["step", "id"],
                "unique_together": {("project_investment", "step", "approver_user")},
            },
        ),
        migrations.AddIndex(
            model_name="investmentprojectapprovalconfigstep",
            index=models.Index(fields=["config", "step"], name="invprojcfg_step_cfg_step_idx"),
        ),
        migrations.AddIndex(
            model_name="investmentprojectapprovalconfigstepapprover",
            index=models.Index(fields=["step", "approver_user"], name="invprojcfg_step_appr_idx"),
        ),
        migrations.AddIndex(
            model_name="projectinvestmentapproval",
            index=models.Index(fields=["tenant", "project_investment"], name="invpiapp_tenant_pi_idx"),
        ),
        migrations.AddIndex(
            model_name="projectinvestmentapproval",
            index=models.Index(fields=["tenant", "decision"], name="invpiapp_tenant_dec_idx"),
        ),
        migrations.AddIndex(
            model_name="projectinvestmentapproval",
            index=models.Index(fields=["approver_recipient_id"], name="invpiapp_recipient_idx"),
        ),
        migrations.AddIndex(
            model_name="projectinvestmentapproval",
            index=models.Index(fields=["gateway_message_id"], name="invpiapp_gateway_msg_idx"),
        ),
    ]
