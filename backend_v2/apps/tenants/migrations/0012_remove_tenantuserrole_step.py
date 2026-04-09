from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tenants", "0011_tenantintegrationconfig_portal_feedback"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="tenantuserrole",
            name="step",
        ),
    ]
