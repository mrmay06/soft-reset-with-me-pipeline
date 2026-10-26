import json
import unittest
from unittest.mock import patch

from modules import script_agent as short
from modules.tts import _build_tts_input


class HookReviewTests(unittest.TestCase):
    def review(self, **changes):
        return {"passes": True, "hook_is_concrete": True, "hook_promise_matches": True,
                "sections_support_core_claim": True, "signature_line_distinctive": True,
                "signature_line_quote": "They haven't asked you one.",
                "psychological_claims_calibrated": True, "viewer_agency_preserved": True,
                "fairness_preserved": True, "generic_drift_sections": [], **changes}

    script = {"hook": "Third date. You've asked seven questions. They haven't asked you one."}

    def test_review_prompt_asks_sonnet_to_judge_the_hook(self):
        prompt = short._argument_review_prompt(self.script, {})
        self.assertIn('"hook_is_concrete"', prompt)

    def test_review_rejects_a_hook_sonnet_calls_abstract(self):
        for response, expected in ((self.review(), True), (self.review(hook_is_concrete=False), False),
                                   ({k: v for k, v in self.review().items() if k != "hook_is_concrete"}, False)):
            with self.subTest(expected=expected), patch.object(short, "_call_script_model", return_value=response):
                result = short._check_argument_coherence(self.script, {}, {"script_model": "test"})
                self.assertIs(result["passes"], expected)


class NarrationPacingTests(unittest.TestCase):
    def test_style_does_not_ask_for_a_pause_after_every_thought(self):
        style = _build_tts_input({"hook": "One line.", "tension": "Two.", "insight": "Three.", "loopback": "Four."}).split("\n\n")[0]
        self.assertNotIn("pause after each thought", style.lower())
        self.assertIn("no long pauses", style.lower())

    def test_shorts_narration_is_not_slowed_down(self):
        with open("config/pipeline_config.json") as handle:
            self.assertEqual(json.load(handle)["tts_speed"], 1.0)


if __name__ == "__main__":
    unittest.main()
