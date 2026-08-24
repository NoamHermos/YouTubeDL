import os
import unittest
from unittest.mock import patch

os.environ["DOWNLOAD_RETENTION_DAYS"] = "0"

from youtube_downloader_web import create_app


class WebApiProtectionTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self.headers = {"X-YouTube-Downloader": "1"}

    def test_mutating_api_requires_client_marker(self):
        response = self.client.post("/api/jobs", json={})
        self.assertEqual(response.status_code, 403)

    def test_marked_invalid_job_reaches_normal_validation(self):
        response = self.client.post("/api/jobs", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "URL is required")

    @patch("youtube_downloader_web.routes.create_job_record", return_value="test-job")
    def test_marked_valid_job_is_accepted(self, create_job_record):
        response = self.client.post(
            "/api/jobs",
            json={"url": "https://www.youtube.com/watch?v=owned", "download_type": "video"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"id": "test-job"})
        create_job_record.assert_called_once()

    def test_read_only_api_remains_available(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/files").status_code, 200)


if __name__ == "__main__":
    unittest.main()
