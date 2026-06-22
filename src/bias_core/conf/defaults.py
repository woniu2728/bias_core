from pathlib import Path

from bias_core.conf.bootstrap import SiteBootstrapConfig, load_site_bootstrap

# Core required Django apps
CORE_REQUIRED_APPS = [
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
    "django_extensions",
    "channels",
    "bias_core",
]

CORE_REQUIRED_MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "bias_core.middleware.StartupStateMiddleware",
    "bias_core.middleware.ExtensionErrorHandlingMiddleware",
    "bias_core.middleware.ExtensionRuntimeInvalidationMiddleware",
    "bias_core.middleware.ExtensionCsrfMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "bias_core.middleware.ExtensionThrottleApiMiddleware",
    "bias_core.middleware.ExtensionRequestMiddleware",
    "bias_core.middleware.QueryLoggingMiddleware",
    "bias_core.middleware.MaintenanceModeMiddleware",
    "bias_core.middleware.SecurityHeadersMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORE_TEMPLATE_LOADERS = [
    "bias_core.extensions.template_loader.ExtensionTemplateLoader",
]


def default_cache_config() -> dict:
    return {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": "redis://localhost:6379/1",
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }


def default_channel_layers() -> dict:
    return {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [("localhost", 6379)],
            },
        }
    }


def default_celery_config(bootstrap: SiteBootstrapConfig | None = None) -> dict:
    if bootstrap and bootstrap.celery_broker_url:
        return {"broker_url": bootstrap.celery_broker_url, "result_backend": bootstrap.celery_result_backend}
    return {
        "broker_url": "redis://localhost:6379/0",
        "result_backend": "redis://localhost:6379/0",
    }
