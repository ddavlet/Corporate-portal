import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0058_request_status_deleted'),
        ('tenants', '0023_tenant_payroll_doc_id_format'),
    ]

    operations = [
        migrations.AddField(
            model_name='request',
            name='source_tenant',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='copied_out_requests',
                to='tenants.tenant',
            ),
        ),
        migrations.AddField(
            model_name='request',
            name='source_request_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='request',
            name='external_matched_tenant',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='externally_matched_requests',
                to='tenants.tenant',
            ),
        ),
        migrations.AddField(
            model_name='request',
            name='external_matched_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='request',
            constraint=models.UniqueConstraint(
                condition=models.Q(('source_request_id__isnull', False), ('source_tenant__isnull', False)),
                fields=('tenant', 'source_tenant', 'source_request_id'),
                name='req_tenant_source_req_uniq',
            ),
        ),
    ]
