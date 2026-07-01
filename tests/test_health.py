from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.conf import settings as django_settings

from bias_core.runtime_state import get_runtime_status, RuntimeState


class HealthCheckApiTests(TestCase):
    def setUp(self):
        super().setUp()
        if not hasattr(django_settings, 'BOOTSTRAP'):
            django_settings.BOOTSTRAP = type('obj', (object,), {'installed': False, 'debug': True})()
        get_runtime_status().state = RuntimeState.READY
    @override_settings(
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "health-test"}},
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
        CELERY_BROKER_URL="memory://",
        SECRET_KEY="health-check-secret-key-1234567890123456",
        NINJA_JWT={"ALGORITHM": "HS256", "SIGNING_KEY": "health-check-jwt-secret-key-1234567890"},
    )
    def test_health_check_exposes_minimal_runtime_status(self):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["state"], "ready")
        self.assertNotIn("readiness", payload)
        self.assertNotIn("database_label", payload)
        self.assertNotIn("cache_driver", payload)

    @override_settings(
        DEBUG=False,
        DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "NAME": "bias", "HOST": "db"}},
        CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "health-prod-test"}},
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
        CELERY_BROKER_URL="memory://",
        SECRET_KEY="django-insecure-change-this-in-production",
        NINJA_JWT={"ALGORITHM": "HS256", "SIGNING_KEY": "short-jwt-secret"},
        FRONTEND_URL="",
        EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend",
    )
    @patch.object(django_settings.BOOTSTRAP, "installed", True)
    @patch("bias_core.runtime_checks._is_test_process", return_value=False)
    def test_health_check_hides_production_runtime_risks(self, _is_test_process):
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("readiness", payload)

    @patch("bias_core.health.collect_health_status")
    def test_health_check_strict_returns_503_for_degraded_payload(self, collect_health_status):
        collect_health_status.return_value = {
            "status": "degraded",
            "checks": {
                "app": {
                    "status": "ok",
                    "available": True,
                    "message": "Bias API runtime is available.",
                    "state": "ready",
                    "current_version": "0.1.0",
                    "installed_version": "0.1.0",
                },
                "db": {
                    "status": "unavailable",
                    "available": False,
                    "message": "Database connection failed.",
                },
            },
        }

        default_response = self.client.get("/api/health")
        self.assertEqual(default_response.status_code, 200, default_response.content)
        default_payload = default_response.json()
        self.assertFalse(default_payload["strict"])
        self.assertFalse(default_payload["strict_failed"])

        strict_response = self.client.get("/api/health?strict=1")
        self.assertEqual(strict_response.status_code, 503, strict_response.content)
        strict_payload = strict_response.json()
        self.assertTrue(strict_payload["strict"])
        self.assertTrue(strict_payload["strict_failed"])
        self.assertEqual(strict_payload["status"], "degraded")



