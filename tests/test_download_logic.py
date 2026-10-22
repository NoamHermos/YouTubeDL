import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from yt_dlp.utils import DownloadError

from ytdl_core.downloader import (
    MP4_AUTO_FORMAT,
    build_video_format_selector,
    ensure_mp4_working_space,
    estimate_mp4_working_bytes,
    run_download_allowing_optional_subtitle_failure,
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


class OptionalSubtitleFallbackTests(unittest.TestCase):
    def setUp(self):
        self.options = {
            "writesubtitles": False,
            "writeautomaticsub": True,
            "subtitleslangs": ["iw"],
            "subtitlesformat": "best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3"},
                {"key": "FFmpegSubtitlesConvertor", "format": "srt"},
            ],
        }

    @patch("ytdl_core.downloader.run_download_with_fallback")
    def test_media_retries_without_subtitles_after_subtitle_download_error(self, download):
        download.side_effect = [
            DownloadError(
                "ERROR: Unable to download video subtitles for 'iw': "
                "HTTP Error 429: Too Many Requests"
            ),
            None,
        ]

        with patch("builtins.print"):
            result = run_download_allowing_optional_subtitle_failure(
                self.options,
                "https://example.invalid/video",
                subtitle_required=False,
            )

        self.assertFalse(result)
        self.assertEqual(download.call_count, 2)
        retry_options = download.call_args_list[1].args[0]
        self.assertFalse(retry_options["writesubtitles"])
        self.assertFalse(retry_options["writeautomaticsub"])
        self.assertNotIn("subtitleslangs", retry_options)
        self.assertNotIn("subtitlesformat", retry_options)
        self.assertEqual(
            retry_options["postprocessors"],
            [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}],
        )
        self.assertTrue(self.options["writeautomaticsub"])
        self.assertEqual(len(self.options["postprocessors"]), 2)

    @patch("ytdl_core.downloader.run_download_with_fallback")
    def test_subtitle_only_download_does_not_fall_back_to_media(self, download):
        download.side_effect = DownloadError(
            "ERROR: Unable to download video subtitles for 'iw': HTTP Error 429"
        )

        with self.assertRaisesRegex(DownloadError, "video subtitles"):
            run_download_allowing_optional_subtitle_failure(
                self.options,
                "https://example.invalid/video",
                subtitle_required=True,
            )

        download.assert_called_once()

    @patch("ytdl_core.downloader.run_download_with_fallback")
    def test_unrelated_media_failure_is_not_hidden(self, download):
        download.side_effect = DownloadError("ERROR: Requested format is not available")

        with self.assertRaisesRegex(DownloadError, "Requested format"):
            run_download_allowing_optional_subtitle_failure(
                self.options,
                "https://example.invalid/video",
                subtitle_required=False,
            )

        download.assert_called_once()

    @patch("ytdl_core.downloader.run_download_with_fallback")
    def test_success_reports_that_subtitles_were_downloaded(self, download):
        result = run_download_allowing_optional_subtitle_failure(
            self.options,
            "https://example.invalid/video",
            subtitle_required=False,
        )

        self.assertTrue(result)
        download.assert_called_once_with(
            self.options,
            "https://example.invalid/video",
        )


if __name__ == "__main__":
    unittest.main()
