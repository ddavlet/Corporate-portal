from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("requests", "0003_concrete_requests_table"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="request",
            name="requester",
        ),
        migrations.AddField(
            model_name="request",
            name="requester",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="requested_items",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

