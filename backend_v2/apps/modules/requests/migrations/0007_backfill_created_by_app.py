from django.db import migrations


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

