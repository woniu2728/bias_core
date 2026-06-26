"""
Django settings for bias_core test suite.
"""

from pathlib import Path
from bias_core.conf.defaults import CORE_REQUIRED_MIDDLEWARE

BASE_DIR = Path(__file__).resolve().parent.parent
BIAS_EXTENSION_WORKSPACE_ROOT = BASE_DIR.parent

SECRET_KEY = "test-secret-key-for-bias-core"
DEBUG = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "bias_core",
]

try:
    from bias_core.conf import discover_installed_extension_django_apps

    INSTALLED_APPS.extend(discover_installed_extension_django_apps())
except Exception:
    pass

MIDDLEWARE = CORE_REQUIRED_MIDDLEWARE

ROOT_URLCONF = "tests.urls"

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
        "NAME": BASE_DIR / "test_bias_core.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

AUTH_USER_MODEL = "auth.User"

from types import SimpleNamespace
ALLOWED_HOSTS = ["*"]
BOOTSTRAP = SimpleNamespace(
    source="test",
    installed=False,
    debug=True,
    secret_key="test-secret-key-for-bias-core",
    jwt_algorithm="HS256",
    jwt_secret_key="test-jwt-secret-key-for-bias-core",
    frontend_url="",
    site_scheme="http",
    database_mode="sqlite",
    use_redis=False,
    email_backend="django.core.mail.backends.console.EmailBackend",
    email_host="smtp.gmail.com",
    email_port=587,
    email_use_tls=True,
    email_host_user="",
    default_from_email="noreply@bias.local",
)
SITE_SCHEME = "http"

NINJA_JWT = {
    "ALGORITHM": "HS256",
    "SIGNING_KEY": "test-jwt-secret-key-for-bias-core",
    "ACCESS_TOKEN_LIFETIME": 900,
    "REFRESH_TOKEN_LIFETIME": 86400,
}
