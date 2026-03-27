from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0007_backfill_created_by_app"),
    ]

    operations = [
        migrations.AlterField(
            model_name="request",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_requests",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="vendor",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_vendors",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

