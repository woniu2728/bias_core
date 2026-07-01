from tests.common import *

from bias_core.storage_service import get_storage_backend, get_storage_metrics, reset_storage_metrics


class StorageMetricsTests(TestCase):
    def setUp(self):
        reset_storage_metrics()
        self.media_dir = make_workspace_temp_dir()
        self.addCleanup(lambda: shutil.rmtree(self.media_dir, ignore_errors=True))

    @override_settings(MEDIA_URL="/media/")
    def test_storage_backend_records_upload_and_delete_metrics(self):
        backend = get_storage_backend(
            {
                "storage_driver": "local",
                "storage_local_path": str(self.media_dir),
                "storage_local_base_url": "/media/",
            }
        )

        file_url = backend.save_bytes("avatars/1/avatar.png", b"avatar", content_type="image/png")
        deleted = backend.delete(file_url)

        self.assertTrue(deleted)
        metrics = get_storage_metrics()
        self.assertEqual(metrics["upload_count"], 1)
        self.assertEqual(metrics["delete_count"], 1)
        self.assertEqual(metrics["operation_count"], 2)
        self.assertEqual(metrics["total_bytes"], 6)
        self.assertEqual(metrics["last_driver"], "local")
        self.assertEqual(metrics["last_backend"], "LocalStorageBackend")

    @override_settings(MEDIA_URL="/media/")
    def test_storage_backend_records_delete_miss_as_failure_metric(self):
        backend = get_storage_backend(
            {
                "storage_driver": "local",
                "storage_local_path": str(self.media_dir),
                "storage_local_base_url": "/media/",
            }
        )

        deleted = backend.delete_key("missing.txt")

        self.assertFalse(deleted)
        metrics = get_storage_metrics()
        self.assertEqual(metrics["delete_failure_count"], 1)
        self.assertEqual(metrics["failure_count"], 1)
        self.assertEqual(metrics["failure_rate"], 1.0)
