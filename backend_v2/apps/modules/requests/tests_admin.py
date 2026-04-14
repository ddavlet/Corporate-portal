from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.modules.requests.admin import UserRequestApprovalAdmin
from apps.modules.requests.models import UserRequestApproval


class UserRequestApprovalAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_site = AdminSite()
        self.admin = UserRequestApprovalAdmin(UserRequestApproval, self.admin_site)
        self.user_model = get_user_model()

    def test_superuser_can_change_user_request_approval(self):
        superuser = self.user_model.objects.create_user(
            username="root_admin",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        request = self.factory.get("/admin/")
        request.user = superuser

        self.assertTrue(self.admin.has_change_permission(request))

    def test_non_superuser_cannot_change_user_request_approval(self):
        staff_user = self.user_model.objects.create_user(
            username="tenant_admin",
            password="x",
            is_staff=True,
            is_superuser=False,
        )
        request = self.factory.get("/admin/")
        request.user = staff_user

        self.assertFalse(self.admin.has_change_permission(request))

    def test_admin_form_exposes_all_editable_model_fields(self):
        request = self.factory.get("/admin/")
        request.user = self.user_model.objects.create_user(
            username="root_for_form",
            password="x",
            is_staff=True,
            is_superuser=True,
        )

        form_class = self.admin.get_form(request)
        form_fields = set(form_class.base_fields.keys())
        editable_model_fields = {
            field.name for field in UserRequestApproval._meta.fields if field.editable and not field.auto_created
        }

        self.assertSetEqual(form_fields, editable_model_fields)
