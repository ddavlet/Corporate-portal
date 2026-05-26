# Payroll payment type: migrate salary requests off cash; seed form/approval configs.

from django.db import migrations, models

SALARY_CATEGORY = "Зарплата/Аванс/Премия"
CASH = "Наличные"
PAYROLL = "Начисление ЗП"

_PAYMENT_TYPE_CHOICES = [
    ("Наличные", "Наличные"),
    ("Перечисление", "Перечисление"),
    ("Пополнение", "Пополнение"),
    ("Платежная карта", "Платежная карта"),
    ("Начисление ЗП", "Начисление ЗП"),
]


def _form_pt_defaults(cash_pt):
    return {
        "is_enabled": cash_pt.is_enabled,
        "default_title": cash_pt.default_title,
        "default_company_payer": cash_pt.default_company_payer,
        "default_description": cash_pt.default_description,
        "default_amount": cash_pt.default_amount,
        "default_currency": cash_pt.default_currency,
        "default_urgency": cash_pt.default_urgency,
        "default_billing_days_offset": cash_pt.default_billing_days_offset,
        "default_payment_purpose": cash_pt.default_payment_purpose,
        "default_vendor_id": cash_pt.default_vendor_id,
        "contracts_required": cash_pt.contracts_required,
    }


def _copy_form_config(apps, cash_pt, payroll_pt):
    RequestFormPaymentTypeRequester = apps.get_model("requests", "RequestFormPaymentTypeRequester")
    RequestFormPaymentTypeVendor = apps.get_model("requests", "RequestFormPaymentTypeVendor")
    RequestPaymentPurposeConfig = apps.get_model("requests", "RequestPaymentPurposeConfig")

    for row in RequestFormPaymentTypeRequester.objects.filter(payment_type_config_id=cash_pt.id):
        RequestFormPaymentTypeRequester.objects.get_or_create(
            payment_type_config_id=payroll_pt.id,
            user_id=row.user_id,
        )
    for row in RequestFormPaymentTypeVendor.objects.filter(payment_type_config_id=cash_pt.id):
        RequestFormPaymentTypeVendor.objects.get_or_create(
            payment_type_config_id=payroll_pt.id,
            vendor_id=row.vendor_id,
        )
    for purpose in RequestPaymentPurposeConfig.objects.filter(
        payment_type_config_id=cash_pt.id,
        category=SALARY_CATEGORY,
    ):
        RequestPaymentPurposeConfig.objects.get_or_create(
            payment_type_config_id=payroll_pt.id,
            name=purpose.name,
            defaults={"category": purpose.category, "is_active": purpose.is_active},
        )
        if purpose.is_active:
            purpose.is_active = False
            purpose.save(update_fields=["is_active"])


def _copy_approval_config(apps, cash_pt, payroll_pt):
    RequestApprovalStepConfig = apps.get_model("requests", "RequestApprovalStepConfig")
    RequestApprovalStepApproverConfig = apps.get_model("requests", "RequestApprovalStepApproverConfig")

    for step in RequestApprovalStepConfig.objects.filter(payment_type_config_id=cash_pt.id):
        payroll_step, _ = RequestApprovalStepConfig.objects.get_or_create(
            payment_type_config_id=payroll_pt.id,
            step=step.step,
            defaults={
                "step_type": step.step_type,
                "is_enabled": step.is_enabled,
                "payment_action_mode": step.payment_action_mode,
                "payment_webapp_url": step.payment_webapp_url,
                "telegram_chat_id": step.telegram_chat_id,
            },
        )
        for appr in RequestApprovalStepApproverConfig.objects.filter(step_config_id=step.id):
            RequestApprovalStepApproverConfig.objects.get_or_create(
                step_config_id=payroll_step.id,
                approver_user_id=appr.approver_user_id,
            )


def migrate_payroll_payment_type_forward(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    Request.objects.filter(payment_type=CASH, category=SALARY_CATEGORY).update(payment_type=PAYROLL)

    RequestPaymentPurposeConfig = apps.get_model("requests", "RequestPaymentPurposeConfig")
    AutoRequestTemplate = apps.get_model("requests", "AutoRequestTemplate")
    salary_purpose_names = set(
        RequestPaymentPurposeConfig.objects.filter(
            payment_type_config__payment_type=CASH,
            category=SALARY_CATEGORY,
        ).values_list("name", flat=True)
    )
    if salary_purpose_names:
        for template in AutoRequestTemplate.objects.filter(payment_type=CASH):
            if (template.payment_purpose or "").strip() in salary_purpose_names:
                template.payment_type = PAYROLL
                template.save(update_fields=["payment_type"])

    RequestFormConfig = apps.get_model("requests", "RequestFormConfig")
    RequestFormPaymentTypeConfig = apps.get_model("requests", "RequestFormPaymentTypeConfig")
    for cfg in RequestFormConfig.objects.all():
        cash_pt = RequestFormPaymentTypeConfig.objects.filter(config_id=cfg.id, payment_type=CASH).first()
        if not cash_pt:
            continue
        payroll_pt, _ = RequestFormPaymentTypeConfig.objects.get_or_create(
            config_id=cfg.id,
            payment_type=PAYROLL,
            defaults=_form_pt_defaults(cash_pt),
        )
        _copy_form_config(apps, cash_pt, payroll_pt)

    RequestApprovalConfig = apps.get_model("requests", "RequestApprovalConfig")
    RequestApprovalPaymentTypeConfig = apps.get_model("requests", "RequestApprovalPaymentTypeConfig")
    for cfg in RequestApprovalConfig.objects.all():
        cash_pt = RequestApprovalPaymentTypeConfig.objects.filter(config_id=cfg.id, payment_type=CASH).first()
        if not cash_pt:
            continue
        payroll_pt, _ = RequestApprovalPaymentTypeConfig.objects.get_or_create(
            config_id=cfg.id,
            payment_type=PAYROLL,
            defaults={
                "is_enabled": cash_pt.is_enabled,
                "request_not_required_rules": cash_pt.request_not_required_rules,
            },
        )
        _copy_approval_config(apps, cash_pt, payroll_pt)


class Migration(migrations.Migration):

    dependencies = [
        ("requests", "0052_request_req_tenant_submitted_id_idx_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="payment_type",
            field=models.CharField(
                choices=_PAYMENT_TYPE_CHOICES,
                default="Наличные",
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="requestformpaymenttypeconfig",
            name="payment_type",
            field=models.CharField(choices=_PAYMENT_TYPE_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="requestapprovalpaymenttypeconfig",
            name="payment_type",
            field=models.CharField(choices=_PAYMENT_TYPE_CHOICES, max_length=50),
        ),
        migrations.AlterField(
            model_name="autorequesttemplate",
            name="payment_type",
            field=models.CharField(choices=_PAYMENT_TYPE_CHOICES, max_length=50),
        ),
        migrations.RunPython(migrate_payroll_payment_type_forward, migrations.RunPython.noop),
    ]
