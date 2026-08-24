import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ytdl_core.downloader import (
    MP4_AUTO_FORMAT,
    build_video_format_selector,
    ensure_mp4_working_space,
    estimate_mp4_working_bytes,
)


class VideoFormatSelectorTests(unittest.TestCase):
    def setUp(self):
        self.formats = [
            {
                "format_id": "137",
                "ext": "mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "height": 1080,
                "fps": 30,
                "tbr": 4500,
                "filesize": 1_000_000_000,
            },
            {
                "format_id": "22",
                "ext": "mp4",
                "vcodec": "avc1.64001F",
                "acodec": "mp4a.40.2",
                "height": 720,
                "fps": 30,
                "tbr": 2000,
                "filesize": 500_000_000,
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "filesize": 50_000_000,
            },
        ]

    def test_auto_uses_video_only_mp4_with_compatible_audio(self):
        self.assertEqual(build_video_format_selector(self.formats, "best"), MP4_AUTO_FORMAT)
        self.assertTrue(MP4_AUTO_FORMAT.startswith("bv[ext=mp4]+ba[ext=m4a]"))

    def test_video_only_quality_adds_audio(self):
        selector = build_video_format_selector(self.formats, "137")
        self.assertEqual(selector, "137+ba[ext=m4a]/137+ba[acodec^=mp4a]/137")

    def test_combined_quality_is_not_given_duplicate_audio(self):
        self.assertEqual(build_video_format_selector(self.formats, "22"), "22")

    def test_missing_quality_falls_back_to_auto(self):
        self.assertEqual(build_video_format_selector(self.formats, "missing"), MP4_AUTO_FORMAT)

    def test_merge_space_estimate_includes_inputs_and_final_file(self):
        self.assertEqual(estimate_mp4_working_bytes(self.formats, "137"), 2_310_000_000)

    @patch("ytdl_core.downloader.shutil.disk_usage")
    def test_low_disk_space_fails_before_download(self, disk_usage):
        disk_usage.return_value = SimpleNamespace(free=1_000_000_000)
        with self.assertRaisesRegex(RuntimeError, "HOST_DOWNLOADS_DIR"):
            ensure_mp4_working_space(Path("."), self.formats, "137")


if __name__ == "__main__":
    unittest.main()
