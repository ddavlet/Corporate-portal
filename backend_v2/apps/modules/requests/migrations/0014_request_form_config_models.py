from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0005_tenant_telegram_otp_fields"),
        ("requests", "0013_request_status_progress_1_to_5"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RequestFormConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "tenant",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_form_config",
                        to="tenants.tenant",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="updated_request_form_configs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "request_form_configs"},
        ),
        migrations.CreateModel(
            name="RequestFormPaymentTypeConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment_type", models.CharField(choices=[("Наличные", "Наличные"), ("Перечисление", "Перечисление"), ("Пополнение", "Пополнение"), ("Платежная карта", "Платежная карта")], max_length=50)),
                ("is_enabled", models.BooleanField(default=True)),
                (
                    "config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_types",
                        to="requests.requestformconfig",
                    ),
                ),
            ],
            options={"db_table": "request_form_payment_type_configs"},
        ),
        migrations.CreateModel(
            name="RequestFormPaymentTypeRequester",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "payment_type_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allowed_requesters",
                        to="requests.requestformpaymenttypeconfig",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_form_allowed_in_payment_types",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "request_form_payment_type_requesters"},
        ),
        migrations.CreateModel(
            name="RequestFormPaymentTypeVendor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "payment_type_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allowed_vendors",
                        to="requests.requestformpaymenttypeconfig",
                    ),
                ),
                (
                    "vendor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="request_form_allowed_in_payment_types",
                        to="requests.vendor",
                    ),
                ),
            ],
            options={"db_table": "request_form_payment_type_vendors"},
        ),
        migrations.CreateModel(
            name="RequestPaymentPurposeConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("category", models.CharField(default="", max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "payment_type_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_purposes",
                        to="requests.requestformpaymenttypeconfig",
                    ),
                ),
            ],
            options={"db_table": "request_payment_purpose_configs"},
        ),
        migrations.AddConstraint(
            model_name="requestformpaymenttypeconfig",
            constraint=models.UniqueConstraint(fields=("config", "payment_type"), name="req_form_payment_type_config_uniq"),
        ),
        migrations.AddIndex(
            model_name="requestformpaymenttypeconfig",
            index=models.Index(fields=["config", "payment_type"], name="req_form_pt_cfg_idx"),
        ),
        migrations.AddIndex(
            model_name="requestformpaymenttypeconfig",
            index=models.Index(fields=["is_enabled"], name="req_form_pt_enabled_idx"),
        ),
        migrations.AddConstraint(
            model_name="requestformpaymenttyperequester",
            constraint=models.UniqueConstraint(fields=("payment_type_config", "user"), name="req_form_pt_requester_uniq"),
        ),
        migrations.AddIndex(
            model_name="requestformpaymenttyperequester",
            index=models.Index(fields=["payment_type_config"], name="req_form_pt_req_cfg_idx"),
        ),
        migrations.AddIndex(
            model_name="requestformpaymenttyperequester",
            index=models.Index(fields=["user"], name="req_form_pt_req_user_idx"),
        ),
        migrations.AddConstraint(
            model_name="requestformpaymenttypevendor",
            constraint=models.UniqueConstraint(fields=("payment_type_config", "vendor"), name="req_form_pt_vendor_uniq"),
        ),
        migrations.AddIndex(
            model_name="requestformpaymenttypevendor",
            index=models.Index(fields=["payment_type_config"], name="req_form_pt_vendor_cfg_idx"),
        ),
        migrations.AddIndex(
            model_name="requestformpaymenttypevendor",
            index=models.Index(fields=["vendor"], name="req_form_pt_vendor_vendor_idx"),
        ),
        migrations.AddConstraint(
            model_name="requestpaymentpurposeconfig",
            constraint=models.UniqueConstraint(fields=("payment_type_config", "name"), name="req_form_pt_purpose_name_uniq"),
        ),
        migrations.AddIndex(
            model_name="requestpaymentpurposeconfig",
            index=models.Index(fields=["payment_type_config"], name="req_form_purpose_cfg_idx"),
        ),
        migrations.AddIndex(
            model_name="requestpaymentpurposeconfig",
            index=models.Index(fields=["is_active"], name="req_form_purpose_active_idx"),
        ),
    ]

