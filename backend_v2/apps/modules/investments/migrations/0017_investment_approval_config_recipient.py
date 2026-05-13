from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("investments", "0016_investment_approval_return_type_notification"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="investmentapprovalconfig",
            name="invapprcfg_tenant_default_uniq",
        ),
        migrations.RemoveConstraint(
            model_name="investmentapprovalconfig",
            name="invapprcfg_tenant_type_uniq",
        ),
        migrations.AddField(
            model_name="investmentapprovalconfig",
            name="recipient",
            field=models.CharField(
                blank=True,
                choices=[("инвестор", "Инвестор"), ("партнер", "Партнер")],
                help_text="Если пусто — цепочка для всех получателей в рамках выбранного типа выплаты (или глобально).",
                max_length=20,
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="investmentapprovalconfig",
            constraint=models.UniqueConstraint(
                condition=Q(return_type__isnull=True, recipient__isnull=True),
                fields=("tenant",),
                name="invapprcfg_tenant_default_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="investmentapprovalconfig",
            constraint=models.UniqueConstraint(
                condition=Q(return_type__isnull=False, recipient__isnull=True),
                fields=("tenant", "return_type"),
                name="invapprcfg_tenant_type_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="investmentapprovalconfig",
            constraint=models.UniqueConstraint(
                condition=Q(return_type__isnull=False, recipient__isnull=False),
                fields=("tenant", "return_type", "recipient"),
                name="invapprcfg_tenant_type_recip_uniq",
            ),
        ),
        migrations.AddConstraint(
            model_name="investmentapprovalconfig",
            constraint=models.UniqueConstraint(
                condition=Q(return_type__isnull=True, recipient__isnull=False),
                fields=("tenant", "recipient"),
                name="invapprcfg_tenant_recip_global_uniq",
            ),
        ),
    ]
