from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cashier", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
ALTER TABLE cashier_cashrevenue ADD COLUMN IF NOT EXISTS received_from varchar(255) NOT NULL DEFAULT '';
ALTER TABLE cashier_cashrevenue ADD COLUMN IF NOT EXISTS payment_method varchar(50) NOT NULL DEFAULT 'cash';
ALTER TABLE cashier_cashrevenue ADD COLUMN IF NOT EXISTS reference_no varchar(80) NOT NULL DEFAULT '';
ALTER TABLE cashier_cashrevenue ADD COLUMN IF NOT EXISTS status varchar(30) NOT NULL DEFAULT 'posted';
ALTER TABLE cashier_cashrevenue ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '[]'::jsonb;
""",
                    reverse_sql="""
ALTER TABLE cashier_cashrevenue DROP COLUMN IF EXISTS received_from;
ALTER TABLE cashier_cashrevenue DROP COLUMN IF EXISTS payment_method;
ALTER TABLE cashier_cashrevenue DROP COLUMN IF EXISTS reference_no;
ALTER TABLE cashier_cashrevenue DROP COLUMN IF EXISTS status;
ALTER TABLE cashier_cashrevenue DROP COLUMN IF EXISTS tags;
""",
                )
            ],
            state_operations=[
                migrations.AddField(
                    model_name="cashrevenue",
                    name="received_from",
                    field=models.CharField(blank=True, default="", max_length=255),
                ),
                migrations.AddField(
                    model_name="cashrevenue",
                    name="payment_method",
                    field=models.CharField(blank=True, default="cash", max_length=50),
                ),
                migrations.AddField(
                    model_name="cashrevenue",
                    name="reference_no",
                    field=models.CharField(blank=True, default="", max_length=80),
                ),
                migrations.AddField(
                    model_name="cashrevenue",
                    name="status",
                    field=models.CharField(blank=True, default="posted", max_length=30),
                ),
                migrations.AddField(
                    model_name="cashrevenue",
                    name="tags",
                    field=models.JSONField(blank=True, default=list),
                ),
            ],
        ),
    ]

