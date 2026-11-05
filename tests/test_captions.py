import unittest
from unittest.mock import patch

from ytdl_core.captions import get_best_subs_config


class OriginalAutomaticCaptionTests(unittest.TestCase):
    def test_explicit_english_original_track_beats_translated_base_code(self):
        info = {
            "automatic_captions": {
                "en": [{"url": "https://example.invalid/captions?tlang=en"}],
                "en-orig": [{"url": "https://example.invalid/captions"}],
            }
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["en-orig"])
        self.assertTrue(config["writeautomaticsub"])

    def test_explicit_original_code_wins_even_if_base_format_looks_original(self):
        info = {
            "automatic_captions": {
                "en": [{"url": "https://example.invalid/ambiguous"}],
                "en-orig": [{"url": "https://example.invalid/original"}],
            }
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["en-orig"])

    def test_legacy_original_english_code_still_works(self):
        info = {
            "automatic_captions": {
                "en": [{"url": "https://example.invalid/original"}],
            }
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["en"])

    def test_explicit_hebrew_original_track_is_preferred(self):
        info = {
            "automatic_captions": {
                "iw": [{"url": "https://example.invalid/captions?tlang=iw"}],
                "iw-orig": [{"url": "https://example.invalid/original"}],
            }
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["iw-orig"])


if __name__ == "__main__":
    unittest.main()
