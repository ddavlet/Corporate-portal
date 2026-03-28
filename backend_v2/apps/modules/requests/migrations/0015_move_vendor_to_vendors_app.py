from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _migrate_vendors_and_links(apps, schema_editor):
    OldVendor = apps.get_model("requests", "Vendor")
    NewVendor = apps.get_model("vendors", "Vendor")
    RequestFormPaymentTypeVendor = apps.get_model("requests", "RequestFormPaymentTypeVendor")
    Request = apps.get_model("requests", "Request")

    if not OldVendor.objects.exists():
        # Нет данных в старом справочнике — переносить нечего. Чистим связи «разрешённые
        # поставщики» в конфиге формы (ID всё равно указывали на старую таблицу).
        RequestFormPaymentTypeVendor.objects.all().delete()
    else:
        mapping = {}
        for ov in OldVendor.objects.all():
            inn_val = f"LEG-{ov.pk}"
            if len(inn_val) > 20:
                inn_val = inn_val[-20:]
            nv = NewVendor(
                tenant_id=ov.tenant_id,
                kind="transfer",
                name=ov.name,
                inn=inn_val,
                account_number=ov.account_number or None,
                created_at=ov.created_at,
                created_by_id=ov.created_by_id,
            )
            nv.save()
            mapping[ov.pk] = nv.pk

        for link in RequestFormPaymentTypeVendor.objects.exclude(vendor_id__isnull=True):
            new_id = mapping.get(link.vendor_id)
            if new_id:
                link.vendor_new_id = new_id
                link.save(update_fields=["vendor_new_id"])

        RequestFormPaymentTypeVendor.objects.filter(vendor_new_id__isnull=True).delete()

        for r in Request.objects.exclude(vendor="").iterator(chunk_size=500):
            name = (r.vendor or "").strip()
            if not name:
                continue
            kind = "cash" if r.payment_type == "Наличные" else "transfer"
            nv = (
                NewVendor.objects.filter(tenant_id=r.tenant_id, kind=kind, name=name)
                .order_by("id")
                .first()
            )
            if nv:
                r.vendor_ref_id = nv.pk
                r.save(update_fields=["vendor_ref_id"])


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0014_request_form_config_models"),
        ("vendors", "0002_enable_vendors_for_requests_tenants"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="requestformpaymenttypevendor",
            name="vendor_new",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="+",
                to="vendors.vendor",
            ),
        ),
        migrations.AddField(
            model_name="request",
            name="vendor_ref",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="requests",
                to="vendors.vendor",
            ),
        ),
        migrations.RunPython(_migrate_vendors_and_links, _noop),
        migrations.RemoveField(
            model_name="requestformpaymenttypevendor",
            name="vendor",
        ),
        migrations.RenameField(
            model_name="requestformpaymenttypevendor",
            old_name="vendor_new",
            new_name="vendor",
        ),
        migrations.AlterField(
            model_name="requestformpaymenttypevendor",
            name="vendor",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="request_form_allowed_in_payment_types",
                to="vendors.vendor",
            ),
        ),
        migrations.DeleteModel(
            name="Vendor",
        ),
    ]
