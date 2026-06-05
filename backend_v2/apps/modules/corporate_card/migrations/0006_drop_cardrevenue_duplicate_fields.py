from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("corporate_card", "0005_cardrevenue_consolidate_legacy_fields"),
    ]

    operations = [
        migrations.RemoveField(model_name="cardrevenue", name="revenue_date"),
        migrations.RemoveField(model_name="cardrevenue", name="direction"),
        migrations.RemoveField(model_name="cardrevenue", name="organization"),
        migrations.RemoveField(model_name="cardrevenue", name="unit"),
        migrations.RemoveField(model_name="cardrevenue", name="employee"),
        migrations.RemoveField(model_name="cardrevenue", name="cash_type"),
        migrations.RemoveField(model_name="cardrevenue", name="account"),
        migrations.RemoveField(model_name="cardrevenue", name="source_year"),
        migrations.RemoveField(model_name="cardrevenue", name="title"),
        migrations.RemoveField(model_name="cardrevenue", name="amount"),
        migrations.RemoveField(model_name="cardrevenue", name="note"),
    ]
