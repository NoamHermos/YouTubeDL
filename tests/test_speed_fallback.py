import unittest
from unittest.mock import patch

from yt_dlp.utils import DownloadError

import ytdl_core.speed as speed


class FakeYoutubeDL:
    def __init__(self, download_action):
        self.download_action = download_action

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def download(self, _urls):
        return self.download_action()


class SpeedFallbackTests(unittest.TestCase):
    def test_postprocessing_failure_is_not_retried(self):
        calls = []

        def factory(_options):
            calls.append(1)
            return FakeYoutubeDL(lambda: (_ for _ in ()).throw(DownloadError("Postprocessing: Conversion failed")))

        with patch.object(speed.yt_dlp, "YoutubeDL", side_effect=factory), patch("builtins.print"):
            with self.assertRaisesRegex(DownloadError, "Conversion failed"):
                speed.run_download_with_fallback({}, "https://example.invalid/video")
        self.assertEqual(len(calls), 1)

    def test_fragment_failure_falls_back_once(self):
        calls = []

        def fail_fast(options):
            options["logger"].error("HTTP Error 403")
            raise DownloadError("ABORT_SPEED_MODE_TRIGGERED")

        def factory(options):
            calls.append(1)
            return FakeYoutubeDL((lambda: fail_fast(options)) if len(calls) == 1 else lambda: None)

        with patch.object(speed.yt_dlp, "YoutubeDL", side_effect=factory), patch("builtins.print"):
            speed.run_download_with_fallback({}, "https://example.invalid/video")
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
