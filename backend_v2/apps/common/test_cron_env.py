import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CRON_DIR = Path(settings.BASE_DIR) / "cron"


class CronJobEnvironmentTests(SimpleTestCase):
    """Regression test: every backend_cron job failed with "settings.DATABASES is
    improperly configured" because cron starts jobs with an empty environment, so
    POSTGRES_* from docker-compose never reached manage.py. Missing daily CBU rates
    (25.08–22.10.2026) made investor reports drop investments.
    """

    def _crontab_bash_env(self) -> str:
        match = re.search(r"^BASH_ENV=(\S+)$", (CRON_DIR / "crontab").read_text(), re.MULTILINE)
        self.assertIsNotNone(match, "crontab must set BASH_ENV so jobs load the container env")
        return match.group(1)

    def test_entrypoint_writes_env_file_that_crontab_loads(self):
        entrypoint = (CRON_DIR / "entrypoint.sh").read_text()
        env_file = self._crontab_bash_env()
        self.assertIn(f"CRON_ENV_FILE={env_file}\n", entrypoint)
        self.assertIn('export -p > "$CRON_ENV_FILE"', entrypoint)
        self.assertLess(entrypoint.index("export -p"), entrypoint.index("exec cron -f"))

    @unittest.skipUnless(shutil.which("bash") and shutil.which("env"), "bash is required")
    def test_job_with_empty_environment_sees_container_vars(self):
        tricky_password = "p@ss $HOME \"q\" 'x' `id` \\ end"
        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "cron.env")
            subprocess.run(
                ["bash", "-c", 'export -p > "$1"', "_", env_file],
                env={"PATH": os.environ.get("PATH", ""), "POSTGRES_DB": "kolberg", "POSTGRES_PASSWORD": tricky_password},
                check=True,
            )
            # Mirrors cron: no inherited environment, only the crontab's BASH_ENV.
            result = subprocess.run(
                ["env", "-i", f"BASH_ENV={env_file}", shutil.which("bash"), "-c",
                 'printf "%s\\n%s" "$POSTGRES_DB" "$POSTGRES_PASSWORD"'],
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertEqual(result.stdout, f"kolberg\n{tricky_password}")
