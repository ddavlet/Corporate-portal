from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('requests', '0065_merge_20260914_2009'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='request',
            name='req_tenant_source_req_uniq',
        ),
        migrations.RemoveField(
            model_name='request',
            name='source_tenant',
        ),
        migrations.RemoveField(
            model_name='request',
            name='source_request_id',
        ),
        migrations.RemoveField(
            model_name='request',
            name='external_matched_tenant',
        ),
        migrations.RemoveField(
            model_name='request',
            name='external_matched_at',
        ),
    ]
