from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0037_requestattachment"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RequestApprovalPurposeExceptionConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(blank=True, default="", max_length=200)),
                ("is_enabled", models.BooleanField(default=True)),
                (
                    "payment_type_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="purpose_exceptions",
                        to="requests.requestapprovalpaymenttypeconfig",
                    ),
                ),
            ],
            options={
                "db_table": "request_approval_purpose_exception_configs",
            },
        ),
        migrations.CreateModel(
            name="RequestApprovalPurposeExceptionStepConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("step", models.IntegerField()),
                ("step_type", models.CharField(choices=[("serial", "serial"), ("payment", "payment")], default="serial", max_length=10)),
                ("is_enabled", models.BooleanField(default=True)),
                ("payment_action_mode", models.CharField(choices=[("callback", "callback"), ("webapp", "webapp"), ("create", "create")], default="callback", max_length=12)),
                ("payment_webapp_url", models.TextField(blank=True, default="")),
                (
                    "exception_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="steps",
                        to="requests.requestapprovalpurposeexceptionconfig",
                    ),
                ),
            ],
            options={
                "db_table": "request_approval_purpose_exception_step_configs",
            },
        ),
        migrations.CreateModel(
            name="RequestApprovalPurposeExceptionPurpose",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "exception_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="purposes",
                        to="requests.requestapprovalpurposeexceptionconfig",
                    ),
                ),
                (
                    "payment_purpose",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approval_purpose_exceptions",
                        to="requests.requestpaymentpurposeconfig",
                    ),
                ),
                (
                    "payment_type_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="purpose_exception_purpose_links",
                        to="requests.requestapprovalpaymenttypeconfig",
                    ),
                ),
            ],
            options={
                "db_table": "request_approval_purpose_exception_purposes",
            },
        ),
        migrations.CreateModel(
            name="RequestApprovalPurposeExceptionStepApproverConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "approver_user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="request_approval_purpose_exception_step_approver_configs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "step_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="approvers",
                        to="requests.requestapprovalpurposeexceptionstepconfig",
                    ),
                ),
            ],
            options={
                "db_table": "request_approval_purpose_exception_step_approver_configs",
            },
        ),
        migrations.AddConstraint(
            model_name="requestapprovalpurposeexceptionpurpose",
            constraint=models.UniqueConstraint(
                fields=("exception_config", "payment_purpose"),
                name="req_appr_exc_purpose_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="requestapprovalpurposeexceptionpurpose",
            constraint=models.UniqueConstraint(
                fields=("payment_type_config", "payment_purpose"),
                name="req_appr_exc_pt_purpose_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="requestapprovalpurposeexceptionstepapproverconfig",
            constraint=models.UniqueConstraint(
                fields=("step_config", "approver_user"),
                name="req_appr_exc_step_approver_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="requestapprovalpurposeexceptionstepconfig",
            constraint=models.UniqueConstraint(
                fields=("exception_config", "step"),
                name="req_appr_exc_step_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionconfig",
            index=models.Index(fields=["payment_type_config"], name="req_appr_exc_pt_idx"),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionconfig",
            index=models.Index(fields=["payment_type_config", "is_enabled"], name="req_appr_exc_enabled_idx"),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionpurpose",
            index=models.Index(fields=["exception_config"], name="req_appr_exc_purpose_exc_idx"),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionpurpose",
            index=models.Index(fields=["payment_type_config"], name="req_appr_exc_purpose_pt_idx"),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionstepapproverconfig",
            index=models.Index(fields=["step_config"], name="req_appr_exc_step_appr_idx"),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionstepconfig",
            index=models.Index(fields=["exception_config", "step"], name="req_appr_exc_step_idx"),
        ),
        migrations.AddIndex(
            model_name="requestapprovalpurposeexceptionstepconfig",
            index=models.Index(fields=["exception_config"], name="req_appr_exc_steps_exc_idx"),
        ),
    ]
