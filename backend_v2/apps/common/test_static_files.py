import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from whitenoise.middleware import WhiteNoiseMiddleware


class AdminStaticFilesTests(SimpleTestCase):
    """Regression test: /api/admin/ was served without CSS because static assets
    were neither routed by Traefik nor served by Django in production (no
    WhiteNoise, no collectstatic step). See docs/SECURITY_ISSUES.md #17.
    """

    def test_whitenoise_middleware_is_installed_before_session_middleware(self):
        middleware = settings.MIDDLEWARE
        self.assertIn("whitenoise.middleware.WhiteNoiseMiddleware", middleware)
        self.assertLess(
            middleware.index("whitenoise.middleware.WhiteNoiseMiddleware"),
            middleware.index("django.contrib.sessions.middleware.SessionMiddleware"),
        )

    def test_collected_admin_static_asset_is_served_by_whitenoise(self):
        # WhiteNoise scans STATIC_ROOT once, at middleware construction time, so the
        # middleware instance must be built *inside* the override_settings block,
        # after collectstatic has populated the (temporary) STATIC_ROOT.
        with tempfile.TemporaryDirectory() as static_root:
            with override_settings(STATIC_ROOT=Path(static_root)):
                call_command("collectstatic", "--noinput", verbosity=0)
                middleware = WhiteNoiseMiddleware(
                    get_response=lambda request: HttpResponse(status=404)
                )
                request = RequestFactory().get(settings.STATIC_URL + "admin/css/base.css")
                response = middleware(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("Content-Type", ""))
