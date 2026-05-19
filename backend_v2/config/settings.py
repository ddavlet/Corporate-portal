from pathlib import Path
import os


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes", "on"}

# RFC-valid Docker DNS alias for the backend (hyphens only). Compose attaches this to ``backend_v2``
# so internal HTTP clients can use ``http://kolberg-django-v2:8001/`` instead of ``django_v2``
# (underscores make Host invalid per RFC 1034/1035 — Django rejects before ALLOWED_HOSTS).
# Optional override: ``DOCKER_INTERNAL_BACKEND_DNS_NAME`` (must stay RFC-valid if set).
DOCKER_INTERNAL_BACKEND_DNS_NAME = (
    (os.getenv("DOCKER_INTERNAL_BACKEND_DNS_NAME") or "kolberg-django-v2").strip()
    or "kolberg-django-v2"
)


def _allowed_hosts_from_env() -> list[str]:
    """Hosts Django accepts on incoming requests.

    Internal callbacks (tg-gateway → backend) use Docker DNS. Legacy names ``django_v2`` /
    ``backend_v2`` are kept in this list for compatibility; ``RewriteDockerInternalHostMiddleware``
    rewrites them to :attr:`DOCKER_INTERNAL_BACKEND_DNS_NAME`, which must also be allowed here.
    """
    hosts = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h] or ["*"]
    if "*" in hosts:
        return hosts
    internal_service_hosts = ("django_v2", "backend_v2", DOCKER_INTERNAL_BACKEND_DNS_NAME)
    return list(dict.fromkeys(list(hosts) + list(internal_service_hosts)))


ALLOWED_HOSTS = _allowed_hosts_from_env()


# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # API
    "rest_framework",
    "rest_framework_simplejwt",

    # Tenant-only backend
    "apps.accounts",
    "apps.tenants",
    "apps.modules.requests",
    "apps.modules.vendors",
    "apps.modules.wallets",
    "apps.modules.cashier",
    "apps.modules.bank_expenses",
    "apps.modules.corporate_card",
    "apps.modules.notes",
    "apps.modules.n8n_integration",
    "apps.modules.telegram_approvals",
    "apps.modules.payroll",
    "apps.modules.feedback",
    "apps.modules.clients_debt",
    "apps.modules.investments",
    "apps.modules.budgets",
    "apps.modules.contracts",
    "apps.modules.reports",

    # MCP server
    "apps.mcp_server",
    "apps.mcp_server.oauth",
]

MIDDLEWARE = [
    "apps.tenants.middleware.RewriteDockerInternalHostMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",

    # n8n internal API: tenant from Host subdomain (before TenantSubdomainMiddleware).
    "apps.modules.n8n_integration.middleware.N8nIntegrationTenantMiddleware",
    "apps.tenants.middleware.TenantSubdomainMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"


# Tenant identification
BASE_DOMAIN = os.getenv("BASE_DOMAIN", "").strip().lower()
TENANT_SUBDOMAIN_FALLBACK = True

# Cookies / CSRF for subdomains (admin POST needs trusted origins)
if BASE_DOMAIN:
    _is_localhost = BASE_DOMAIN in ("localhost", "127.0.0.1")
    if not _is_localhost:
        SESSION_COOKIE_DOMAIN = "." + BASE_DOMAIN.lstrip(".")
        CSRF_COOKIE_DOMAIN = "." + BASE_DOMAIN.lstrip(".")
    CSRF_TRUSTED_ORIGINS = [
        f"https://*.{BASE_DOMAIN.lstrip('.')}",
    ]
    if DEBUG:
        CSRF_TRUSTED_ORIGINS += [
            f"http://*.{BASE_DOMAIN.lstrip('.')}",
            f"http://{BASE_DOMAIN.lstrip('.')}",
        ]


# Database
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", ""),
        "USER": os.getenv("POSTGRES_USER", ""),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
        "HOST": os.getenv("POSTGRES_HOST", "db"),
        "PORT": int(os.getenv("POSTGRES_PORT", "5432")),
    }
}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATIC_DIR = BASE_DIR / "static"
STATICFILES_DIRS = [STATIC_DIR] if STATIC_DIR.exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"

#
# User-uploaded files (served via auth-protected DRF endpoints).
#
MEDIA_URL = os.getenv("DJANGO_MEDIA_URL", "/media/")
MEDIA_ROOT = BASE_DIR / os.getenv("DJANGO_MEDIA_ROOT", "media")

# Keep filesystem-based storage so the download endpoint can stream files via `FileResponse`.
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"


# DRF + JWT
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

# n8n integration API (path prefix + shared secret)
def _normalize_n8n_url_path(raw: str) -> str:
    """Single URL segment or multi-segment path; no leading/trailing slashes (env may use e.g. n8n/ or /n8n/)."""
    s = (raw or "").strip().strip("/")
    parts = [p for p in s.split("/") if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return "n8n"
    return "/".join(parts)


N8N_INTEGRATION_URL_PATH = _normalize_n8n_url_path(os.getenv("N8N_INTEGRATION_URL_PATH", "n8n"))
N8N_INTEGRATION_URL_PREFIX = f"/api/{N8N_INTEGRATION_URL_PATH}/"
# When env keeps a legacy path, also mount at /api/n8n/ so clients and Traefik can use one URL.
_n8n_mount = [N8N_INTEGRATION_URL_PATH]
if N8N_INTEGRATION_URL_PATH != "n8n":
    _n8n_mount.append("n8n")
N8N_INTEGRATION_MOUNT_PATHS = list(dict.fromkeys(_n8n_mount))
N8N_INTEGRATION_URL_PREFIXES = frozenset(
    f"/api/{seg}".rstrip("/") for seg in N8N_INTEGRATION_MOUNT_PATHS
)
N8N_INTEGRATION_TOKEN = os.getenv("N8N_INTEGRATION_TOKEN", "").strip()

# Internal base URL for n8n webhook calls (skips Traefik+TLS when backend and n8n share a docker network).
# Example: http://n8n:5678/webhook -> backend builds http://n8n:5678/webhook/<tenant>/<endpoint>.
# When empty, backend falls back to the public https://{subdomain}.{BASE_DOMAIN} path.
N8N_INTERNAL_BASE_URL = (os.getenv("N8N_INTERNAL_BASE_URL", "") or "").strip().rstrip("/")

# MCP server: OAuth issuer + MCP protocol base (e.g. https://api.kolberg.uz/mcp).
MCP_BASE_URL = (os.getenv("MCP_BASE_URL", "") or "").strip().rstrip("/") or (
    f"https://api.{BASE_DOMAIN}/mcp" if BASE_DOMAIN else "http://localhost:8000/mcp"
)
# Protected resource identifier (Streamable HTTP MCP endpoint).
MCP_RESOURCE_URL = (os.getenv("MCP_RESOURCE_URL", "") or "").strip().rstrip("/") or MCP_BASE_URL

def _mcp_public_origin() -> str:
    from urllib.parse import urlparse

    parsed = urlparse(MCP_BASE_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


# Django OTP login — under /mcp/oauth/login/ (ASGI excludes it from FastMCP; works with Traefik PathPrefix /mcp).
MCP_OAUTH_LOGIN_URL = (os.getenv("MCP_OAUTH_LOGIN_URL", "") or "").strip().rstrip("/") or (
    f"{_mcp_public_origin()}/mcp/oauth/login"
)

# Origins allowed for Streamable HTTP (Claude.ai connector).
_default_mcp_origins = f"{_mcp_public_origin()},https://claude.ai,https://claude.com"
MCP_ALLOWED_ORIGINS = [
    o.strip()
    for o in (os.getenv("MCP_ALLOWED_ORIGINS", _default_mcp_origins) or _default_mcp_origins).split(",")
    if o.strip()
]

# Outbound authorization token for calling n8n webhooks (X-N8N-Token header).
N8N_TOKEN = os.getenv("N8N_TOKEN", "").strip()

# Portal feedback: path on tenant host, e.g. https://lemonfit.kolberg.uz/n8n/ai/dispatch/
N8N_FEEDBACK_AI_WEBHOOK_PATH = (
    os.getenv("N8N_FEEDBACK_AI_WEBHOOK_PATH", "n8n/ai/dispatch") or "n8n/ai/dispatch"
).strip().strip("/")
MESSAGING_GATEWAY_SEND_URL = os.getenv("MESSAGING_GATEWAY_SEND_URL", "").strip()
MESSAGING_GATEWAY_ADMIN_URL = os.getenv("MESSAGING_GATEWAY_ADMIN_URL", "http://tg_gateway:8080").strip()
# Platform-neutral actions for tg-gateway (tenant-wide; subdomain only scopes HTTP API / tenant row).
MESSAGING_GATEWAY_SEND_ACTION = os.getenv("MESSAGING_GATEWAY_SEND_ACTION", "send_interactive").strip()
MESSAGING_GATEWAY_EDIT_ACTION = os.getenv("MESSAGING_GATEWAY_EDIT_ACTION", "edit_interactive").strip()
MESSAGING_GATEWAY_DRAFT_ACTION = os.getenv("MESSAGING_GATEWAY_DRAFT_ACTION", "send").strip()

# Reports payload cache (seconds). Keep short to reduce staleness while smoothing n8n latency spikes.
REPORTS_CACHE_TTL_SECONDS = int(os.getenv("REPORTS_CACHE_TTL_SECONDS", "60"))


