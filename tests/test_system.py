from tests.common import *

from bias_core.runtime_state import get_runtime_status, RuntimeState


class SystemStatusApiTests(TestCase):
    def setUp(self):
        super().setUp()
        get_runtime_status().state = RuntimeState.READY

    def test_system_status_endpoint_returns_ready_state(self):
        response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["state"], "ready")
        self.assertIn("current_version", payload)

