from datetime import date

from django.db import migrations, models


def forwards_fill_billing_date(apps, schema_editor):
    InvestReturn = apps.get_model("investments", "InvestReturn")
    for row in InvestReturn.objects.all().iterator():
        d = row.date
        if d is None:
            continue
        bd = date(d.year, d.month, 1)
        InvestReturn.objects.filter(pk=row.pk).update(billing_date=bd)


class Migration(migrations.Migration):
    dependencies = [
        ("investments", "0014_investmentformconfig"),
    ]

    operations = [
        migrations.AddField(
            model_name="investreturn",
            name="billing_date",
            field=models.DateField(null=True, blank=True, help_text="Первый день месяца начисления (PnL и отчёты по месяцу назначения, как у заявок)."),
        ),
        migrations.RunPython(forwards_fill_billing_date, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="investreturn",
            name="billing_date",
            field=models.DateField(help_text="Первый день месяца начисления (PnL и отчёты по месяцу назначения, как у заявок)."),
        ),
        migrations.AddIndex(
            model_name="investreturn",
            index=models.Index(fields=["tenant", "billing_date"], name="invret_tenant_billing_idx"),
        ),
    ]
