import django.db.models.deletion
from django.db import migrations, models

from apps.common.index_migrations import drop_fk_index_operation


CASCADE = django.db.models.deletion.CASCADE


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0032_investreturn_payout_schedule"),
        ("tenants", "0023_tenant_payroll_doc_id_format"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="investmentapprovalconfigstep",
            name="invcfg_step_cfg_step_idx",
        ),
        migrations.RemoveIndex(
            model_name="investmentapprovalconfigstepapprover",
            name="invcfg_step_appr_idx",
        ),
        migrations.RemoveIndex(
            model_name="investmentprojectapprovalconfigstep",
            name="invprojcfg_step_cfg_step_idx",
        ),
        migrations.RemoveIndex(
            model_name="investmentprojectapprovalconfigstepapprover",
            name="invprojcfg_step_appr_idx",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="investreturn",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="invest_returns",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="investpayoutschedule",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="invest_payout_schedules",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="projectinvestment",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="project_investments",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="investcompany",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="invest_companies",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="investpayoutschedulesharelink",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="invest_schedule_share_links",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="investmentapprovalconfigstep",
                    name="config",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="steps",
                        to="investments.investmentapprovalconfig",
                    ),
                ),
                migrations.AlterField(
                    model_name="investmentapprovalconfigstepapprover",
                    name="step",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="step_approvers",
                        to="investments.investmentapprovalconfigstep",
                    ),
                ),
                migrations.AlterField(
                    model_name="investmentreturnapproval",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="investment_return_approvals",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="investmentreturnapproval",
                    name="invest_return",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="approvals",
                        to="investments.investreturn",
                    ),
                ),
                migrations.AlterField(
                    model_name="investpayoutnotificationlog",
                    name="schedule",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="notification_logs",
                        to="investments.investpayoutschedule",
                    ),
                ),
                migrations.AlterField(
                    model_name="investmentprojectapprovalconfigstep",
                    name="config",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="steps",
                        to="investments.investmentprojectapprovalconfig",
                    ),
                ),
                migrations.AlterField(
                    model_name="investmentprojectapprovalconfigstepapprover",
                    name="step",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="step_approvers",
                        to="investments.investmentprojectapprovalconfigstep",
                    ),
                ),
                migrations.AlterField(
                    model_name="projectinvestmentapproval",
                    name="tenant",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="project_investment_approvals",
                        to="tenants.tenant",
                    ),
                ),
                migrations.AlterField(
                    model_name="projectinvestmentapproval",
                    name="project_investment",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=CASCADE,
                        related_name="approvals",
                        to="investments.projectinvestment",
                    ),
                ),
            ],
            database_operations=[
                drop_fk_index_operation(
                    ("investments", "InvestReturn", "tenant"),
                    ("investments", "InvestPayoutSchedule", "tenant"),
                    ("investments", "ProjectInvestment", "tenant"),
                    ("investments", "InvestCompany", "tenant"),
                    ("investments", "InvestPayoutScheduleShareLink", "tenant"),
                    ("investments", "InvestmentApprovalConfigStep", "config"),
                    ("investments", "InvestmentApprovalConfigStepApprover", "step"),
                    ("investments", "InvestmentReturnApproval", "tenant"),
                    ("investments", "InvestmentReturnApproval", "invest_return"),
                    ("investments", "InvestPayoutNotificationLog", "schedule"),
                    ("investments", "InvestmentProjectApprovalConfigStep", "config"),
                    ("investments", "InvestmentProjectApprovalConfigStepApprover", "step"),
                    ("investments", "ProjectInvestmentApproval", "tenant"),
                    ("investments", "ProjectInvestmentApproval", "project_investment"),
                ),
            ],
        ),
    ]
