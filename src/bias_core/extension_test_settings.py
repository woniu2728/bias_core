"""
Shared Django settings for Bias extension test suites.

Extension repositories can point pytest-django at this module instead of
duplicating a local settings.py that drifts from the workspace extension graph.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from bias_core.conf.defaults import CORE_REQUIRED_MIDDLEWARE
from bias_core.conf.extension_discovery import discover_extension_django_configuration


def _has_extension_manifests(path: Path) -> bool:
    return any(path.glob("*/extension.json")) or any(path.glob("bias-ext-*/extension.json"))


def _resolve_workspace_root() -> Path:
    configured = os.getenv("BIAS_EXTENSION_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "extension.json").exists():
        return cwd.parent
    for candidate in (cwd, cwd.parent):
        if _has_extension_manifests(candidate):
            return candidate

    package_dir = Path(__file__).resolve().parent
    for candidate in package_dir.parents:
        if _has_extension_manifests(candidate):
            return candidate
    return cwd


BASE_DIR = _resolve_workspace_root()
BIAS_EXTENSION_WORKSPACE_ROOT = BASE_DIR
BIAS_FRONTEND_DIR = BASE_DIR / "bias" / "frontend"
BIAS_EXTENSION_PACKAGE_DISCOVERY = True

SECRET_KEY = "test-secret-key-for-bias-extensions"
DEBUG = True
ALLOWED_HOSTS = ["*"]

EXTENSION_DJANGO_CONFIGURATION = discover_extension_django_configuration(BASE_DIR)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "ninja",
    "ninja_extra",
    "ninja_jwt",
    "corsheaders",
    "channels",
    "bias_core",
    *EXTENSION_DJANGO_CONFIGURATION["installed_apps"],
]

MIGRATION_MODULES = EXTENSION_DJANGO_CONFIGURATION["migration_modules"]
MIDDLEWARE = CORE_REQUIRED_MIDDLEWARE
ROOT_URLCONF = "bias_core.extension_test_urls"
TEST_RUNNER = "bias_core.test_runner.BiasDiscoverRunner"
ASGI_APPLICATION = "bias_core.routing.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_bias_extensions.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

AUTH_USER_MODEL = str(EXTENSION_DJANGO_CONFIGURATION.get("auth_user_model") or "auth.User")
FRONTEND_URL = "http://localhost:5173"
SITE_SCHEME = "http"
DEFAULT_FROM_EMAIL = "Bias <noreply@example.com>"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
EMAIL_HOST = ""
EMAIL_PORT = 587
EMAIL_USE_TLS = False
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = "test-mail-password"

BOOTSTRAP = SimpleNamespace(
    source="test",
    installed=True,
    debug=True,
    secret_key=SECRET_KEY,
    jwt_algorithm="HS256",
    jwt_secret_key="test-jwt-secret-key-for-bias-extensions",
    frontend_url=FRONTEND_URL,
    site_scheme=SITE_SCHEME,
    database_mode="sqlite",
    use_redis=False,
    email_backend=EMAIL_BACKEND,
    email_host=EMAIL_HOST,
    email_port=EMAIL_PORT,
    email_use_tls=EMAIL_USE_TLS,
    email_host_user=EMAIL_HOST_USER,
    default_from_email=DEFAULT_FROM_EMAIL,
)

NINJA_JWT = {
    "ALGORITHM": "HS256",
    "SIGNING_KEY": BOOTSTRAP.jwt_secret_key,
    "ACCESS_TOKEN_LIFETIME": 900,
    "REFRESH_TOKEN_LIFETIME": 86400,
}
