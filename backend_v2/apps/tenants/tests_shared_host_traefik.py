import re
from pathlib import Path

from django.test import SimpleTestCase

_SHARED_API_RULE = re.compile(r"traefik\.http\.routers\.django-v2-shared-api\.rule=(.+)$", re.MULTILINE)
_COMPOSE_VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


class SharedHostApiRouterTests(SimpleTestCase):
    """The shared portal host must not expose n8n. settings.py mounts n8n at /api/n8n/ and at
    /api/<N8N_INTEGRATION_URL_PATH>/, so the Traefik rule has to exclude both prefixes.
    """

    def _rule(self, env: dict[str, str]) -> str:
        compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        if not compose.exists():
            self.skipTest("docker-compose.yml not available (backend_v2-only checkout)")
        match = _SHARED_API_RULE.search(compose.read_text())
        self.assertIsNotNone(match, "django-v2-shared-api router is missing")
        # Same substitution docker compose does for ${VAR:-default}.
        return _COMPOSE_VAR.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), match.group(1))

    def _excluded_prefixes(self, env: dict[str, str]) -> set[str]:
        return set(re.findall(r"!PathPrefix\(`([^`]*)`\)", self._rule(env)))

    def test_default_n8n_path_is_excluded(self):
        excluded = self._excluded_prefixes({})
        for prefix in ("/api/n8n/", "/api/messaging-gateway/", "/api/admin/"):
            self.assertIn(prefix, excluded)

    def test_custom_n8n_path_is_excluded(self):
        excluded = self._excluded_prefixes({"N8N_INTEGRATION_URL_PATH": "legacy-integration"})
        self.assertIn("/api/legacy-integration/", excluded)
        self.assertIn("/api/n8n/", excluded)


_ROUTER_LABEL = re.compile(r"traefik\.http\.routers\.([\w-]+)\.(\w+(?:\.\w+)?)=(.+)$", re.MULTILINE)
_SHARED_ROUTER_VAR = "PORTAL_SHARED_HOST_ROUTER"
_EXPECTED_SHARED_ROUTERS = {
    "django-v2-shared-api",
    "django-v2-shared-static",
    "django-v2-shared-tg-chats",
    "django-v2-shared-tg-bot-setup",
    "frontend-v2-shared",
    "frontend-v2-shared-root",
}


class SharedHostRoutersSetTests(SimpleTestCase):
    """The set of Traefik routers that answer on the shared portal host (plan crit. 22)."""

    def _routers(self) -> dict[str, dict[str, str]]:
        compose = Path(__file__).resolve().parents[3] / "docker-compose.yml"
        if not compose.exists():
            self.skipTest("docker-compose.yml not available (backend_v2-only checkout)")
        routers: dict[str, dict[str, str]] = {}
        for name, key, value in _ROUTER_LABEL.findall(compose.read_text()):
            routers.setdefault(name, {})[key] = value.strip()
        return routers

    def _on_shared_host(self) -> dict[str, dict[str, str]]:
        return {n: r for n, r in self._routers().items() if _SHARED_ROUTER_VAR in r.get("rule", "")}

    def test_exactly_the_expected_routers_answer_on_the_shared_host(self):
        self.assertEqual(set(self._on_shared_host()), _EXPECTED_SHARED_ROUTERS)

    def test_every_shared_router_has_a_certresolver_and_tls(self):
        for name, router in self._on_shared_host().items():
            with self.subTest(router=name):
                self.assertTrue(router.get("tls.certresolver"))
                self.assertEqual(router.get("tls"), "true")

    def test_shared_rules_match_the_host_and_never_n8n_mcp_or_webhook(self):
        for name, router in self._on_shared_host().items():
            with self.subTest(router=name):
                rule = router["rule"]
                self.assertIn("Host(`${" + _SHARED_ROUTER_VAR, rule)
                # A positive match is forbidden; "!PathPrefix" exclusions are fine.
                positive = re.sub(r"!PathPrefix\(`[^`]*`\)", "", rule)
                for forbidden in ("/mcp", "/.well-known", "/api/n8n", "/api/messaging-gateway/webhook", "/api/admin"):
                    self.assertNotIn(forbidden, positive)

    def test_n8n_mcp_and_webhook_routers_do_not_list_the_shared_host(self):
        for name, router in self._routers().items():
            if name in _EXPECTED_SHARED_ROUTERS:
                continue
            with self.subTest(router=name):
                self.assertNotIn(_SHARED_ROUTER_VAR, router.get("rule", ""))
