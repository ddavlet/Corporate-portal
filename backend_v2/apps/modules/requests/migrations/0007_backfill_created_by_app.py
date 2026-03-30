from django.db import migrations


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
    Request = apps.get_model("requests", "Request")
    Vendor = apps.get_model("requests", "Vendor")

    Request.objects.filter(created_by__isnull=True).update(created_by=app_user)
    Vendor.objects.filter(created_by__isnull=True).update(created_by=app_user)


def backwards(apps, schema_editor):
    Request = apps.get_model("requests", "Request")
    Vendor = apps.get_model("requests", "Vendor")

    Request.objects.update(created_by=None)
    Vendor.objects.update(created_by=None)


class Migration(migrations.Migration):
    dependencies = [
        ("requests", "0006_vendor_and_created_by"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]

