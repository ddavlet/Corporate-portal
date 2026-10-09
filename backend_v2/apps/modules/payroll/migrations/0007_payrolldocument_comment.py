# Hand-written: branch-only model change (make makemigrations runs against main).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("payroll", "0006_document_workflow_and_payouts"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrolldocument",
            name="comment",
            field=models.TextField(blank=True, default=""),
        ),
    ]
