from django.test import TestCase, override_settings
from django.test.client import RequestFactory
from django.http import Http404

from apps.tenants.middleware import TenantSubdomainMiddleware
from apps.tenants.models import Tenant


@override_settings(BASE_DOMAIN="example.com", TENANT_SUBDOMAIN_FALLBACK=True, ALLOWED_HOSTS=["*"])
class TenantSubdomainMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.tenant = Tenant.objects.create(
            name="Acme",
            subdomain="acme",
            is_active=True,
        )

    def test_attaches_tenant_for_known_subdomain(self):
        req = self.factory.get("/api/health/", HTTP_HOST="acme.example.com")

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        res = mw(req)

        self.assertTrue(hasattr(res, "tenant"))
        self.assertEqual(res.tenant.id, self.tenant.id)

    def test_404_for_unknown_subdomain(self):
        req = self.factory.get("/api/health/", HTTP_HOST="unknown.example.com")

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        with self.assertRaises(Http404):
            mw(req)

    def test_404_when_host_has_no_subdomain(self):
        req = self.factory.get("/api/health/", HTTP_HOST="example.com")

        def get_response(request):
            return request

        mw = TenantSubdomainMiddleware(get_response)
        with self.assertRaises(Http404):
            mw(req)

