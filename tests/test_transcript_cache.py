import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import web_worker
from ytdl_core.transcript_cache import import_browser_transcript, write_cached_transcript, youtube_video_id


VIDEO_ID = "AbCdEf123_-"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"
EXPORT_TEXT = (
    f"YouTube transcript\nVideo ID: {VIDEO_ID}\nLanguage: iw\nCaptions: auto-generated\n\n"
    "[0:00] שלום עולם\n[0:03] זוהי בדיקת תמלול\n"
)


class TranscriptCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / ".transcript-cache"
        self.export = self.root / "browser-export.txt"
        self.export.write_text(EXPORT_TEXT, encoding="utf-8")

    def import_sample(self):
        return import_browser_transcript(self.export, "Sample / video", self.cache)

    def test_import_retains_identity_and_creates_continuous_utf8_text(self):
        cache_file = self.import_sample()
        record = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertEqual(record["video_id"], VIDEO_ID)
        self.assertEqual(record["source"], "browser-export")
        self.assertEqual(record["language"], "iw")
        with patch("builtins.print"):
            output = write_cached_transcript(VIDEO_URL, self.root / "job", self.cache)
        self.assertEqual(output.name, "Sample video.iw.txt")
        self.assertEqual(output.read_text(encoding="utf-8"), "שלום עולם זוהי בדיקת תמלול\n")

    def test_other_video_or_untrusted_host_cannot_use_transcript(self):
        self.import_sample()
        for url in (
            "https://www.youtube.com/watch?v=ZyXwVu987_-",
            f"https://example.invalid/watch?v={VIDEO_ID}",
            "https://www.youtube.com/watch?v=../outside",
            "http://[invalid",
        ):
            with self.subTest(url=url):
                self.assertIsNone(write_cached_transcript(url, self.root / "job", self.cache))

    def test_short_video_url_maps_to_same_id(self):
        self.assertEqual(youtube_video_id(f"https://youtu.be/{VIDEO_ID}?t=2"), VIDEO_ID)

    def test_empty_or_invalid_export_is_rejected(self):
        for content in ("arbitrary text", EXPORT_TEXT.split("[0:00]")[0], EXPORT_TEXT.replace(VIDEO_ID, "../outside")):
            with self.subTest(content=content):
                self.export.write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.import_sample()

    def test_corrupt_or_mismatched_cache_is_ignored(self):
        cache_file = self.import_sample()
        for content in ("not JSON", json.dumps({"video_id": "ZyXwVu987_-", "source": "browser-export"})):
            with self.subTest(content=content), patch("builtins.print"):
                cache_file.write_text(content, encoding="utf-8")
                self.assertIsNone(write_cached_transcript(VIDEO_URL, self.root / "job", self.cache))

    def test_cached_txt_job_succeeds_without_contacting_youtube(self):
        self.import_sample()
        args = web_worker.build_parser().parse_args([
            "--url", VIDEO_URL, "--download-type", "txt", "--downloads-dir", str(self.root / ".extension-jobs" / "job"),
        ])
        with patch.dict("os.environ", {"DOWNLOADS_DIR": str(self.root)}), patch.object(web_worker, "fetch_info") as fetch_info, patch("builtins.print"):
            self.assertEqual(web_worker.run_job(args), 0)
        fetch_info.assert_not_called()
        self.assertTrue((self.root / ".extension-jobs" / "job" / "Sample video.iw.txt").is_file())

    def test_media_and_srt_jobs_keep_the_normal_download_flow(self):
        self.import_sample()
        for mode in ("video", "audio", "srt"):
            args = web_worker.build_parser().parse_args(["--url", VIDEO_URL, "--download-type", mode])
            with self.subTest(mode=mode), patch.object(web_worker, "write_cached_transcript") as cached, patch.object(web_worker, "fetch_info", side_effect=RuntimeError("normal lookup")), patch("builtins.print"):
                with self.assertRaisesRegex(RuntimeError, "normal lookup"):
                    web_worker.run_job(args)
                cached.assert_not_called()


if __name__ == "__main__":
    unittest.main()
