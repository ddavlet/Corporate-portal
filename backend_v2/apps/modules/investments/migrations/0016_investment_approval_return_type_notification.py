from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("investments", "0015_investreturn_billing_date"),
    ]

    operations = [
        migrations.AddField(
            model_name="investmentapprovalconfig",
            name="return_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("дивиденды", "Дивиденды"),
                    ("проценты", "Проценты"),
                    ("доля_прибыли", "Доля прибыли"),
                    ("тело_инвестиций", "Тело инвестиций"),
                ],
                help_text="Если пусто — конфиг по умолчанию для всех типов выплат без отдельной настройки.",
                max_length=25,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="investmentapprovalconfig",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="investment_approval_configs",
                to="tenants.tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="investmentapprovalconfig",
            constraint=models.UniqueConstraint(
                condition=Q(return_type__isnull=True),
                fields=("tenant",),
                name="invapprcfg_tenant_default_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="investmentapprovalconfig",
            constraint=models.UniqueConstraint(
                condition=Q(return_type__isnull=False),
                fields=("tenant", "return_type"),
                name="invapprcfg_tenant_type_uniq",
            ),
        ),
    ]
