from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def _get_or_create_app_user(apps):
    User = apps.get_model("accounts", "User")
    # `accounts.User` historically used `name`, but now it uses `full_name`.
    # In migration execution state can include later renames, so detect dynamically.
    field_names = {f.name for f in User._meta.fields}
    name_field = "name" if "name" in field_names else ("full_name" if "full_name" in field_names else None)
    if not name_field:
        raise RuntimeError("accounts.User must have either 'name' or 'full_name' field.")

    user, created = User.objects.get_or_create(
        username="app",
        defaults={
            name_field: "Система",
            # In migrations we cannot call User methods (historical model). Use unusable password marker.
            "password": "!",
            "is_active": True,
            "is_staff": False,
            "is_superuser": False,
        },
    )
    current_name = getattr(user, name_field, None)
    if current_name != "Система":
        setattr(user, name_field, "Система")
        user.save(update_fields=[name_field])
    if created:
        # Ensure unusable password even if model default differs.
        User.objects.filter(pk=user.pk).update(password="!")
    return user


def forwards(apps, schema_editor):
    app_user = _get_or_create_app_user(apps)
    CashExpense = apps.get_model("cashier", "CashExpense")
    CashRevenue = apps.get_model("cashier", "CashRevenue")

    CashExpense.objects.filter(created_by__isnull=True).update(created_by=app_user)
    CashRevenue.objects.filter(created_by__isnull=True).update(created_by=app_user)


def backwards(apps, schema_editor):
    CashExpense = apps.get_model("cashier", "CashExpense")
    CashRevenue = apps.get_model("cashier", "CashRevenue")

    CashExpense.objects.update(created_by=None)
    CashRevenue.objects.update(created_by=None)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_user_name_field"),
        ("cashier", "0002_cashrevenue_mock_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashexpense",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_cash_expenses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="cashrevenue",
            name="created_by",
            field=models.ForeignKey(
                null=True,
                blank=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_cash_revenues",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="cashexpense",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_cash_expenses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="cashrevenue",
            name="created_by",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="created_cash_revenues",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

