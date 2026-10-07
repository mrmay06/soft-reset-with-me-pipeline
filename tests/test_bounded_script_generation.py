import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import script_agent as short
from utils.script_contract import build_spoken_script_text, spoken_text_hash


class BoundedScriptTests(unittest.TestCase):
    config = {"script_model": "test", "script_min_words": 60, "script_max_words": 90}

    def good(self, **changes):
        return {"hook": "You type the message.", "insight": "Ask what you want to say.",
                "hook_quality": "strong", "engagement_quality": "strong", "word_count_in_range": True,
                "word_count": 80, "validation": "passed", "validation_failures": [], **changes}

    def approved(self, script, *args):
        return {"passes": True, "status": "passed", "spoken_text_sha256": spoken_text_hash(build_spoken_script_text(script))}

    def test_happy_path_is_one_draft_one_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(short, "_validate_script", side_effect=lambda script, config: script), patch.object(
            short, "_call_script_model", return_value=self.good()
        ) as draft, patch.object(short, "_check_argument_coherence", side_effect=self.approved) as review:
            result = short._bounded_script_generation("prompt", {}, self.config, directory)
        draft.assert_called_once()
        review.assert_called_once()
        self.assertEqual(result["generation_attempts"], {"drafts": 1, "reviews": 1})

    def test_issues_are_combined_before_review_and_final_narration_is_approved(self):
        invalid = self.good(hook_quality="weak", engagement_quality="weak", word_count_in_range=False, validation_failures=["superiority_framing"])
        with tempfile.TemporaryDirectory() as directory, patch.object(short, "_validate_script", side_effect=lambda script, config: script), patch.object(
            short, "_call_script_model", side_effect=[invalid, self.good()]
        ) as draft, patch.object(short, "_check_argument_coherence", side_effect=self.approved) as review:
            result = short._bounded_script_generation("prompt", {}, self.config, directory)
        self.assertEqual(draft.call_count, 2)
        review.assert_called_once()
        correction = draft.call_args.args[0]
        for issue in ("weak_hook", "weak_engagement_question", "superiority_framing"):
            self.assertIn(issue, correction)
        self.assertEqual(result["argument_review"]["spoken_text_sha256"], spoken_text_hash(build_spoken_script_text(result)))

    def test_three_bad_drafts_stop_and_save_without_paid_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(short, "_validate_script", side_effect=lambda script, config: script), patch.object(
            short, "_call_script_model", side_effect=lambda *args: self.good(validation_failures=["unsupported_guarantee"])
        ) as draft, patch.object(short, "_check_argument_coherence") as review:
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                short._bounded_script_generation("prompt", {}, self.config, directory)
            saved = json.loads((Path(directory) / "02_script.json").read_text())
            self.assertEqual(saved["validation"], "needs_review")
            self.assertEqual(saved["generation_attempts"], {"drafts": 3, "reviews": 0})
        self.assertEqual(draft.call_count, 3)
        review.assert_not_called()

    def test_two_failed_reviews_stop_without_third_review(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(short, "_validate_script", side_effect=lambda script, config: script), patch.object(
            short, "_call_script_model", side_effect=lambda *args: self.good()
        ) as draft, patch.object(short, "_check_argument_coherence", return_value={"passes": False, "status": "failed"}) as review:
            with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                short._bounded_script_generation("prompt", {}, self.config, directory)
        self.assertEqual(draft.call_count, 2)
        self.assertEqual(review.call_count, 2)

    def test_review_outage_saves_and_stops_without_redrafting(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(short, "_validate_script", side_effect=lambda script, config: script), patch.object(
            short, "_call_script_model", return_value=self.good()
        ) as draft, patch.object(short, "_check_argument_coherence", return_value={"passes": False, "status": "unavailable"}):
            with self.assertRaisesRegex(RuntimeError, "review unavailable"):
                short._bounded_script_generation("prompt", {}, self.config, directory)
            self.assertTrue((Path(directory) / "02_script.json").exists())
        draft.assert_called_once()

    def test_combined_path_never_exceeds_three_drafts_two_reviews(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(short, "_validate_script", side_effect=lambda script, config: script), patch.object(
            short, "_call_script_model", side_effect=[self.good(hook_quality="weak"), self.good(), self.good()]
        ) as draft, patch.object(short, "_check_argument_coherence", side_effect=[{"passes": False, "status": "failed"}, self.approved(self.good())]) as review:
            result = short._bounded_script_generation("prompt", {}, self.config, directory)
        self.assertEqual(draft.call_count, 3)
        self.assertEqual(review.call_count, 2)
        self.assertEqual(result["generation_attempts"], {"drafts": 3, "reviews": 2})


if __name__ == "__main__":
    unittest.main()
