import unittest
from unittest.mock import patch

from ytdl_core.captions import get_best_subs_config, has_subtitles_enabled


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


class LiveChatCaptionSelectionTests(unittest.TestCase):
    def test_hebrew_original_beats_live_chat_and_translated_english(self):
        info = {
            "subtitles": {"live_chat": [{"ext": "json"}]},
            "automatic_captions": {
                "iw-orig": [{"url": "https://example.invalid/original"}],
                "iw": [{"url": "https://example.invalid/captions?tlang=iw"}],
                "en": [{"url": "https://example.invalid/captions?tlang=en"}],
            },
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["iw-orig"])
        self.assertTrue(config["writeautomaticsub"])
        self.assertFalse(config["writesubtitles"])

    def test_live_chat_only_does_not_enable_subtitles(self):
        for source in ("subtitles", "automatic_captions"):
            with self.subTest(source=source), patch("builtins.print"):
                config = get_best_subs_config({source: {"live_chat": [{"ext": "json"}]}})

            self.assertFalse(has_subtitles_enabled(config))
            self.assertNotIn("subtitleslangs", config)

    def test_manual_subtitles_in_other_language_are_still_available(self):
        info = {
            "subtitles": {
                "live_chat": [{"ext": "json"}],
                "pl": [{"ext": "vtt"}],
            }
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["pl"])
        self.assertTrue(config["writesubtitles"])

    def test_hebrew_original_beats_manual_english(self):
        info = {
            "subtitles": {"en": [{"ext": "vtt"}]},
            "automatic_captions": {
                "iw-orig": [{"url": "https://example.invalid/original"}],
            },
        }

        with patch("builtins.print"):
            config = get_best_subs_config(info)

        self.assertEqual(config["subtitleslangs"], ["iw-orig"])


if __name__ == "__main__":
    unittest.main()
