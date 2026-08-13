import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


CASCADE = django.db.models.deletion.CASCADE
PROTECT = django.db.models.deletion.PROTECT
SET_NULL = django.db.models.deletion.SET_NULL


def tenant_fk(related_name):
    return models.ForeignKey(
        db_index=False,
        on_delete=CASCADE,
        related_name=related_name,
        to="tenants.tenant",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0059_request_source_tenant_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveIndex(model_name="approval", name="approvals_request_id_idx"),
        migrations.RemoveIndex(model_name="requestcategory", name="req_cat_tenant_name_idx"),
        migrations.RemoveIndex(model_name="requestformpaymenttypeconfig", name="req_form_pt_cfg_idx"),
        migrations.RemoveIndex(model_name="requestformpaymenttyperequester", name="req_form_pt_req_cfg_idx"),
        migrations.RemoveIndex(model_name="requestformpaymenttyperequester", name="req_form_pt_req_user_idx"),
        migrations.RemoveIndex(model_name="requestformpaymenttypevendor", name="req_form_pt_vendor_cfg_idx"),
        migrations.RemoveIndex(model_name="requestformpaymenttypevendor", name="req_form_pt_vendor_vendor_idx"),
        migrations.RemoveIndex(model_name="requestpaymentpurposeconfig", name="req_form_purpose_cfg_idx"),
        migrations.RemoveIndex(model_name="requestapprovalpaymenttypeconfig", name="req_appr_pt_cfg_idx"),
        migrations.RemoveIndex(model_name="requestapprovalstepconfig", name="req_appr_step_idx"),
        migrations.RemoveIndex(model_name="requestapprovalstepconfig", name="req_appr_steps_by_pt_idx"),
        migrations.RemoveIndex(model_name="requestapprovalstepapproverconfig", name="req_appr_step_approvers_idx"),
        migrations.RemoveIndex(model_name="requestapprovalpurposeexceptionconfig", name="req_appr_exc_pt_idx"),
        migrations.RemoveIndex(
            model_name="requestapprovalpurposeexceptionpurpose",
            name="req_appr_exc_purpose_exc_idx",
        ),
        migrations.RemoveIndex(
            model_name="requestapprovalpurposeexceptionpurpose",
            name="req_appr_exc_purpose_pt_idx",
        ),
        migrations.RemoveIndex(
            model_name="requestapprovalpurposeexceptionstepconfig",
            name="req_appr_exc_step_idx",
        ),
        migrations.RemoveIndex(
            model_name="requestapprovalpurposeexceptionstepconfig",
            name="req_appr_exc_steps_exc_idx",
        ),
        migrations.RemoveIndex(
            model_name="requestapprovalpurposeexceptionstepapproverconfig",
            name="req_appr_exc_step_appr_idx",
        ),
        migrations.AlterField(
            model_name="request",
            name="tenant",
            field=tenant_fk("requests"),
        ),
        migrations.AlterField(
            model_name="requestattachment",
            name="request",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="attachments",
                to="requests.request",
            ),
        ),
        migrations.AlterField(
            model_name="requestattachment",
            name="tenant",
            field=tenant_fk("request_attachments"),
        ),
        migrations.AlterField(
            model_name="approval",
            name="request",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="approvals",
                to="requests.request",
            ),
        ),
        migrations.AlterField(
            model_name="requestcategory",
            name="tenant",
            field=tenant_fk("request_categories"),
        ),
        migrations.AlterField(
            model_name="requestformpaymenttypeconfig",
            name="config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="payment_types",
                to="requests.requestformconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestformpaymenttyperequester",
            name="payment_type_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="allowed_requesters",
                to="requests.requestformpaymenttypeconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestformpaymenttypevendor",
            name="payment_type_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="allowed_vendors",
                to="requests.requestformpaymenttypeconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestpaymentpurposeconfig",
            name="payment_type_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="payment_purposes",
                to="requests.requestformpaymenttypeconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpaymenttypeconfig",
            name="config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="payment_types",
                to="requests.requestapprovalconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalstepconfig",
            name="payment_type_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="steps",
                to="requests.requestapprovalpaymenttypeconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalstepapproverconfig",
            name="step_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="approvers",
                to="requests.requestapprovalstepconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpurposeexceptionconfig",
            name="payment_type_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="purpose_exceptions",
                to="requests.requestapprovalpaymenttypeconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpurposeexceptionpurpose",
            name="exception_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="purposes",
                to="requests.requestapprovalpurposeexceptionconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpurposeexceptionpurpose",
            name="payment_type_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="purpose_exception_purpose_links",
                to="requests.requestapprovalpaymenttypeconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpurposeexceptionstepconfig",
            name="exception_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="steps",
                to="requests.requestapprovalpurposeexceptionconfig",
            ),
        ),
        migrations.AlterField(
            model_name="requestapprovalpurposeexceptionstepapproverconfig",
            name="step_config",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="approvers",
                to="requests.requestapprovalpurposeexceptionstepconfig",
            ),
        ),
        migrations.AlterField(
            model_name="autorequesttemplate",
            name="tenant",
            field=tenant_fk("auto_request_templates"),
        ),
        migrations.AlterField(
            model_name="requestcomment",
            name="request",
            field=models.ForeignKey(
                db_index=False,
                on_delete=CASCADE,
                related_name="comments",
                to="requests.request",
            ),
        ),
    ]
