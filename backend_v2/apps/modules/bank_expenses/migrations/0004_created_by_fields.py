from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def _get_or_create_app_user(apps):
    User = apps.get_model("accounts", "User")
    user, created = User.objects.get_or_create(
        username="app",
        defaults={
            "name": "Система",
            # In migrations we cannot call User methods (historical model). Use unusable password marker.
            "password": "!",
            "is_active": True,
            "is_staff": False,
            "is_superuser": False,
        },
    )
    if user.name != "Система":
        user.name = "Система"
        user.save(update_fields=["name"])
    if created:
        # Ensure unusable password even if model default differs.
        User.objects.filter(pk=user.pk).update(password="!")
    return user


def forwards(apps, schema_editor):
    app_user = _get_or_create_app_user(apps)
    BankExpense = apps.get_model("bank_expenses", "BankExpense")
    BankRevenue = apps.get_model("bank_expenses", "BankRevenue")

    BankExpense.objects.filter(created_by__isnull=True).update(created_by=app_user)
    BankRevenue.objects.filter(created_by__isnull=True).update(created_by=app_user)


def backwards(apps, schema_editor):
    BankExpense = apps.get_model("bank_expenses", "BankExpense")
    BankRevenue = apps.get_model("bank_expenses", "BankRevenue")

    BankExpense.objects.update(created_by=None)
    BankRevenue.objects.update(created_by=None)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_name_field"),
        ("tenants", "0001_initial"),
        ("bank_expenses", "0003_bankrevenue_concrete_schema"),
    ]

    operations = [
        migrations.AddField(
            model_name="bankexpense",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="bankexpense",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_bank_expenses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="bankrevenue",
            name="created_at",
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
        migrations.AddField(
            model_name="bankrevenue",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_bank_revenues",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="bankexpense",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_bank_expenses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="bankrevenue",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_bank_revenues",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

