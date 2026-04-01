from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0025_autorequesttemplate"),
    ]

    operations = [
        migrations.AddField(
            model_name="approval",
            name="message_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
