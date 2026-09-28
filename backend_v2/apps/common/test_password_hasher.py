from django.conf import settings
from django.contrib.auth.hashers import get_hasher
from django.test import SimpleTestCase


class TestRunPasswordHasherTests(SimpleTestCase):
    """Guards CI speed: PBKDF2 in test runs made every create_user(password=...) ~0.25s."""

    def test_test_runs_use_fast_md5_hasher(self):
        self.assertEqual(
            settings.PASSWORD_HASHERS, ["django.contrib.auth.hashers.MD5PasswordHasher"]
        )
        self.assertEqual(get_hasher().algorithm, "md5")
