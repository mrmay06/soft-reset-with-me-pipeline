import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import main
import main_long
from modules import script_agent as short
from modules import longform_script_agent as long
from utils.script_contract import spoken_text_hash


class ReviewFailClosedTests(unittest.TestCase):
    def short_review(self):
        return dict(passes=True, hook_promise_matches=True,
                    sections_support_core_claim=True, signature_line_distinctive=True,
                    signature_line_quote="Ask what you want to say.",
                    psychological_claims_calibrated=True, viewer_agency_preserved=True,
                    fairness_preserved=True, generic_drift_sections=[])

    def long_review(self):
        return dict(passes=True, psychological_claims_calibrated=True,
                    counterpoint_present=True, viewer_agency_preserved=True,
                    counterpoint_quote="Sometimes this is ordinary editing.",
                    decision_tool_present=True, decision_tool_quote="Ask what you want to say.",
                    opening_promise_resolved=True, retention_filler_present=False,
                    drift_chapters=[])

    def test_provider_outage_is_not_approval(self):
        for module, call, review_fn in (
            (short, "_call_script_model", short._check_argument_coherence),
            (long, "_call_model", long._review_script),
        ):
            with self.subTest(module=module.__name__), patch.object(module, call, side_effect=RuntimeError("provider offline")):
                result = review_fn({}, {}, {"script_model": "test"})
                self.assertIs(result["passes"], False)
                self.assertEqual(result["status"], "unavailable")

    def test_only_complete_boolean_approval_passes(self):
        for module, call, review_fn, good in (
            (short, "_call_script_model", short._check_argument_coherence, self.short_review()),
            (long, "_call_model", long._review_script, self.long_review()),
        ):
            cases = [good, {**good, "passes": "false"}, {}, [],
                     {key: value for key, value in good.items() if key not in {"generic_drift_sections", "drift_chapters"}}]
            for index, response in enumerate(cases):
                with self.subTest(module=module.__name__, case=index), patch.object(module, call, return_value=response):
                    script = {"hook": "Ask what you want to say.", "chapters": [{"voiceover": "Sometimes this is ordinary editing. Ask what you want to say."}]}
                    result = review_fn(script, {}, {"script_model": "test"})
                    self.assertIs(result["passes"], index == 0)

    def test_outage_preserves_script_and_stops_before_rewrite(self):
        for module, filename in ((short, "02_script.json"), (long, "02_longform_script.json")):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as directory:
                script = {"hook": "Keep this draft", "argument_review": {"passes": False, "status": "unavailable"}}
                with self.assertRaisesRegex(RuntimeError, "review unavailable"):
                    module._require_available_argument_review(script, directory)
                saved = json.loads((Path(directory) / filename).read_text())
                self.assertEqual(saved["hook"], "Keep this draft")
                self.assertEqual(saved["validation"], "needs_review")
                self.assertTrue(saved["human_review_required"])

    def test_cached_script_cannot_bypass_review(self):
        for gate, filename in ((main._enforce_script_review_gate, "02_script.json"),
                               (main_long._enforce_longform_script_gate, "02_longform_script.json")):
            with tempfile.TemporaryDirectory() as directory:
                for review in (None, {}, {"passes": False, "status": "failed"},
                               {"passes": True, "status": "soft_failed"},
                               {"passes": "true", "status": "passed"}):
                    with self.subTest(filename=filename, review=review):
                        (Path(directory) / filename).write_text(json.dumps({"validation": "forced", "argument_review": review}))
                        with self.assertRaisesRegex(RuntimeError, "argument review"):
                            gate(directory)
                (Path(directory) / filename).write_text(json.dumps({"validation": "forced", "argument_review": {"passes": True, "status": "passed", "spoken_text_sha256": spoken_text_hash("")}}))
                gate(directory)

    def test_missing_or_invalid_script_blocks_media(self):
        for gate, filename in ((main._enforce_script_review_gate, "02_script.json"),
                               (main_long._enforce_longform_script_gate, "02_longform_script.json")):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(RuntimeError):
                    gate(directory)
                (Path(directory) / filename).write_text("[]")
                with self.assertRaises(RuntimeError):
                    gate(directory)

    def test_judge_requires_explicit_consistent_approval(self):
        for gate in (main._enforce_creative_judge_gate, main_long._enforce_creative_judge_gate):
            with tempfile.TemporaryDirectory() as directory:
                for report in ({}, {"passed": "true", "gate": "passed"},
                               {"passed": False, "gate": "failed"},
                               {"passed": True, "gate": "failed"},
                               {"passed": True, "gate": "passed", "hard_failures": ["policy"]}):
                    with self.subTest(report=report):
                        (Path(directory) / "10_judge_report.json").write_text(json.dumps(report))
                        with self.assertRaises(RuntimeError):
                            gate(directory)
                (Path(directory) / "10_judge_report.json").write_text(json.dumps({"passed": True, "gate": "passed", "hard_failures": []}))
                gate(directory)


if __name__ == "__main__":
    unittest.main()
