import io
import logging

from django.test import Client, SimpleTestCase, override_settings
from django.urls import path


def _boom(request):
    raise RuntimeError("boom for logging test")


urlpatterns = [path("boom/", _boom)]


@override_settings(DEBUG=False, ROOT_URLCONF=__name__, MIDDLEWARE=[], ALLOWED_HOSTS=["testserver"])
class ContainerLoggingTests(SimpleTestCase):
    """Production runs with DEBUG off; these records must reach the stream `make logs` reads."""

    def _capture(self, logger_name: str) -> io.StringIO:
        handlers = [h for h in logging.getLogger(logger_name).handlers if isinstance(h, logging.StreamHandler)]
        self.assertTrue(handlers, f"{logger_name} has no stream handler")
        buffer = io.StringIO()
        previous = handlers[0].setStream(buffer)
        self.addCleanup(handlers[0].setStream, previous)
        return buffer

    def test_unhandled_500_traceback_reaches_container_stream(self):
        # Regression: Django's default console handler needs DEBUG on, so this traceback was lost
        # (the silent «Деньги получены» 500s left nothing in the logs).
        buffer = self._capture("django.request")
        res = Client(raise_request_exception=False).get("/boom/")
        self.assertEqual(res.status_code, 500)
        out = buffer.getvalue()
        self.assertIn("Internal Server Error: /boom/", out)
        self.assertIn("RuntimeError: boom for logging test", out)

    def test_client_errors_stay_out_of_the_logs(self):
        buffer = self._capture("django.request")
        res = Client().get("/missing/")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(buffer.getvalue(), "")

    def test_app_warnings_reach_container_stream_with_logger_name(self):
        buffer = self._capture("apps")
        logging.getLogger("apps.modules.cash_withdrawals.telegram").warning("cwr_callback: probe")
        self.assertIn("WARNING apps.modules.cash_withdrawals.telegram cwr_callback: probe", buffer.getvalue())
