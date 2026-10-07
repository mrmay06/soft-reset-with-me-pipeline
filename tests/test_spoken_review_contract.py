import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import main
import main_long
from modules import script_agent as short
from modules import longform_script_agent as long
from utils import strategy
from utils.script_contract import build_spoken_script_text, spoken_text_hash
from tests import test_review_fail_closed as review_fixtures


class SpokenReviewContractTests(unittest.TestCase):
    def test_shared_strategy_cannot_impose_track_word_count(self):
        data = {"version": "test", "script": {"word_count_signal": "Use 45-75 words", "notes": "Keep concrete detail"}}
        with patch.object(strategy, "load_strategy", return_value=data):
            prompt = strategy.inject_strategy("Configured 700-950 words", "script")
        self.assertNotIn("45-75", prompt)
        self.assertIn("700-950", prompt)
        self.assertIn("Keep concrete detail", prompt)
        self.assertEqual(data["script"]["word_count_signal"], "Use 45-75 words")

    def test_reviews_do_not_see_unspoken_supporting_fields(self):
        script = {"hook": "Actual hook.", "editorial_pov": "UNSPOKEN POV",
                  "only_soft_reset_line": "UNSPOKEN SIGNATURE", "counterpoint": "UNSPOKEN COUNTERPOINT",
                  "decision_tool": "UNSPOKEN TOOL", "chapters": [{"id": 1, "purpose": "UNSPOKEN PURPOSE", "voiceover": "Actual chapter."}]}
        short_prompt = short._argument_review_prompt(script, {})
        long_prompt = long._review_prompt(script, {})
        self.assertIn("Actual hook.", short_prompt)
        self.assertIn("Actual chapter.", long_prompt)
        for marker in ("UNSPOKEN POV", "UNSPOKEN SIGNATURE", "UNSPOKEN COUNTERPOINT", "UNSPOKEN TOOL", "UNSPOKEN PURPOSE"):
            self.assertNotIn(marker, short_prompt + long_prompt)

    def test_unspoken_long_counterpoint_or_tool_cannot_pass(self):
        script = {"chapters": [{"voiceover": "Sometimes this is ordinary editing. Ask what you want to say."}]}
        good = review_fixtures.ReviewFailClosedTests().long_review()
        for field in ("counterpoint_quote", "decision_tool_quote"):
            for quote in ("Only stored in metadata.", "", None):
                response = {**good, field: quote}
                with patch.object(long, "_call_model", return_value=response):
                    self.assertFalse(long._review_script(script, {}, {"script_model": "test"})["passes"])

    def test_unspoken_short_signature_cannot_pass(self):
        response = review_fixtures.ReviewFailClosedTests().short_review()
        script = {"hook": "An actual opening.", "only_soft_reset_line": response["signature_line_quote"]}
        with patch.object(short, "_call_script_model", return_value=response):
            self.assertFalse(short._check_argument_coherence(script, {}, {"script_model": "test"})["passes"])

    def test_changed_cached_narration_invalidates_approval(self):
        for gate, filename, text_fn, script in (
            (main._enforce_script_review_gate, "02_script.json", build_spoken_script_text, {"hook": "Original opening."}),
            (main_long._enforce_longform_script_gate, "02_longform_script.json", long._spoken_text, {"chapters": [{"voiceover": "Original narration."}]}),
        ):
            with tempfile.TemporaryDirectory() as directory:
                script["argument_review"] = {"passes": True, "status": "passed", "spoken_text_sha256": spoken_text_hash(text_fn(script))}
                path = Path(directory) / filename
                path.write_text(json.dumps(script))
                gate(directory)
                if "hook" in script:
                    script["hook"] = "Changed opening."
                else:
                    script["chapters"][0]["voiceover"] = "Changed narration."
                path.write_text(json.dumps(script))
                with self.assertRaises(RuntimeError):
                    gate(directory)

    def test_short_approval_is_final_with_no_late_edits(self):
        script = {"hook": "Original hook.", "insight": "Original insight.", "hook_quality": "strong",
                  "engagement_quality": "strong", "word_count_in_range": True, "word_count": 80, "validation": "passed"}
        reviewed = []
        calls = 0

        def validate(value, config):
            nonlocal calls
            calls += 1
            value["word_count_in_range"] = True
            return value

        def review(value, research, config):
            text = build_spoken_script_text(value)
            reviewed.append(text)
            return {"passes": True, "status": "passed", "spoken_text_sha256": spoken_text_hash(text)}

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "01_research.json").write_text('{"topic":"test"}')
            config = {"script_model": "test", "script_min_words": 60, "script_max_words": 90}
            with patch.object(short, "_call_script_model", return_value=script) as generation, patch.object(short, "_validate_script", side_effect=validate), patch.object(short, "_check_argument_coherence", side_effect=review):
                result = short.run_script("test", directory, config)
            self.assertEqual(len(reviewed), 1)
            self.assertEqual(calls, 1)
            generation.assert_called_once()
            self.assertEqual(result["argument_review"]["spoken_text_sha256"], spoken_text_hash(build_spoken_script_text(result)))
            prompt = generation.call_args.args[0]
            self.assertIn("60-90", prompt)
            self.assertNotIn("45-75", prompt)


if __name__ == "__main__":
    unittest.main()
