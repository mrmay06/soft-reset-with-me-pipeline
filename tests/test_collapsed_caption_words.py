import unittest
from utils.caption_validation import merge_collapsed_words, validate_words


class CollapsedCaptionWordTests(unittest.TestCase):
    def test_shared_onset_preserves_text_and_measured_interval(self):
        raw = [{"word": "and", "start": 1, "end": 1},
               {"word": "you", "start": 1, "end": 1.2},
               {"word": "wanted", "start": 1.2, "end": 1.5}]
        result = merge_collapsed_words(raw)
        self.assertEqual(result[0], {"word": "and you", "start": 1, "end": 1.2})
        self.assertEqual(validate_words(result, "and you wanted", 2)["script_coverage"], 1)
        self.assertEqual(raw[0]["word"], "and")

    def test_multiple_collapsed_words_share_next_measured_interval(self):
        result = merge_collapsed_words([{"word": "a", "start": 1, "end": 1},
                                       {"word": "small", "start": 1, "end": 1},
                                       {"word": "thing", "start": 1, "end": 1.4}])
        self.assertEqual(result[0]["word"], "a small thing")
        self.assertEqual(result[0]["end"], 1.4)

    def test_missing_interval_or_different_onset_remains_blocked(self):
        for raw in ([{"word": "a", "start": 1, "end": 1}],
                    [{"word": "a", "start": 1, "end": 1}, {"word": "thing", "start": 1.5, "end": 2}]):
            with self.assertRaises(RuntimeError):
                merge_collapsed_words(raw)
