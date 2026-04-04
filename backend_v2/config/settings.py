from pathlib import Path
import os


# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-change-me")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes", "on"}


ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h] or ["*"]


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
    "apps.modules.cashier",
    "apps.modules.bank_expenses",
    "apps.modules.corporate_card",
    "apps.modules.notes",
    "apps.modules.n8n_integration",
    "apps.modules.telegram_approvals",
    "apps.modules.payroll",
    "apps.modules.feedback",
]

MIDDLEWARE = [
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
    SESSION_COOKIE_DOMAIN = "." + BASE_DOMAIN.lstrip(".")
    CSRF_COOKIE_DOMAIN = "." + BASE_DOMAIN.lstrip(".")
    CSRF_TRUSTED_ORIGINS = [
        f"https://*.{BASE_DOMAIN.lstrip('.')}",
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
TIME_ZONE = "UTC"
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

# Outbound authorization token for calling n8n webhooks (X-N8N-Token header).
N8N_TOKEN = os.getenv("N8N_TOKEN", "").strip()

# Portal feedback: path on tenant host (Traefik → /webhook/<tenant>/<path>), e.g. lemonfit.kolberg.uz/n8n/ai/dispatch
N8N_FEEDBACK_AI_WEBHOOK_PATH = (
    os.getenv("N8N_FEEDBACK_AI_WEBHOOK_PATH", "n8n/ai/dispatch") or "n8n/ai/dispatch"
).strip().strip("/")
# When set (e.g. http://n8n:5678), backend calls n8n inside Docker: {base}/webhook/<tenant>/<path>.
# Avoids hairpin/HTTPS issues when posting from backend_v2 to the tenant public host.
N8N_INTERNAL_BASE_URL = os.getenv("N8N_INTERNAL_BASE_URL", "").strip().rstrip("/")

TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL = os.getenv("TELEGRAM_APPROVALS_BRIDGE_DISPATCH_URL", "").strip()
# Optional override for bridge failure notifications; default is derived from dispatch URL or tenant host + /n8n/error/
TELEGRAM_APPROVALS_BRIDGE_ERROR_URL = os.getenv("TELEGRAM_APPROVALS_BRIDGE_ERROR_URL", "").strip()
TELEGRAM_APPROVALS_BRIDGE_TOKEN = os.getenv("TELEGRAM_APPROVALS_BRIDGE_TOKEN", "").strip()

# Absolute base URL of the requests portal (no trailing slash), for links in draft Telegram notifications.
REQUESTS_PORTAL_PUBLIC_BASE_URL = os.getenv("REQUESTS_PORTAL_PUBLIC_BASE_URL", "").strip()

