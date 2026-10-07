from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch

from modules import research_agent as short
from modules import longform_research_agent as long
from utils.research_evidence import normalize_research_basis


ROOT = Path(__file__).resolve().parents[1]


class ResearchEvidenceTests(unittest.TestCase):
    def test_model_confidence_or_url_cannot_manufacture_verification(self):
        original = {"content_basis": "factual_claim", "confidence_level": "peer_reviewed", "evidence_status": "verified",
                    "source_url": "https://example.com/unfetched-paper", "fact_year": 2026,
                    "source_basis": "A possible explanation"}
        result = normalize_research_basis(original)
        self.assertEqual(result["confidence_level"], "observational")
        self.assertEqual(result["evidence_status"], "unverified")
        self.assertEqual(result["source_url"], "")
        self.assertEqual(result["suggested_source_url"], original["source_url"])
        self.assertIsNone(result["fact_year"])
        self.assertEqual(original["evidence_status"], "verified")
        self.assertEqual(normalize_research_basis(result), result)

    def test_scorer_receives_missing_candidate_context_in_one_call(self):
        candidate = {"topic": "Editing the message", "content_format": "specific_scenario",
                     "emotional_trigger": "typing a message in bed at night then deleting it",
                     "psych_concept": "self-silencing", "confidence_level": "peer_reviewed",
                     "source_basis": "suggested lens", "source_name": "unchecked name",
                     "source_url": "https://example.com/suggestion"}
        raw = {"topic": candidate["topic"], "confidence_level": "peer_reviewed",
               "editorial_seed": "Editing can help you communicate but can also hide what you actually meant.",
               "only_soft_reset_line": "The edit should not erase what you meant.",
               "source_url": "https://example.com/model-citation", "audience_fit_score": 4,
               "emotional_tension_score": 4, "scriptability_score": 4,
               "share_save_score": 4, "safety_brand_score": 4}
        template = (ROOT / "prompts/research_score_prompt.txt").read_text()
        with patch.object(short, "_assert_gemini_key"), patch.object(short, "generate_json", return_value=raw) as model:
            result = short._score_one_candidate(candidate, "test", template)
        model.assert_called_once()
        prompt = model.call_args.args[0]
        for field in ("content_format", "emotional_trigger", "psych_concept"):
            self.assertIn(candidate[field], prompt)
        for field in ("content_format", "emotional_trigger", "psych_concept"):
            self.assertEqual(result[field], candidate[field])
        self.assertEqual(result["evidence_status"], "not_required")
        self.assertEqual(result["source_url"], "")
        self.assertEqual(result["share_save_score"], 4)

    def test_emotional_fallback_does_not_need_a_source(self):
        result = short._fallback_score_candidate({"topic": "Checking the phone",
                                                  "confidence_level": "therapist_consensus",
                                                  "source_url": "https://example.com/unchecked"}, 1)
        self.assertEqual(result["evidence_status"], "not_required")
        self.assertEqual(result["confidence_level"], "observational")
        self.assertEqual(result["source_url"], "")

    def test_long_research_output_cannot_claim_verified_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"research_model": "test", "topic_memory_file": str(Path(directory) / "topics.json"),
                      "performance_memory_file": str(Path(directory) / "performance.json")}
            with patch.object(long, "_generate_longform_topic", return_value={"topic": "Test topic", "confidence_level": "peer_reviewed"}) as model:
                result = long.run_longform_research("test", directory, config)
            model.assert_called_once()
            self.assertEqual(result["evidence_status"], "not_required")
            self.assertEqual(result["confidence_level"], "observational")

    def test_mock_research_uses_same_honest_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            for run in (short.run_research_mock, long.run_longform_research_mock):
                result = run("test", directory, {})
                self.assertEqual(result["evidence_status"], "not_required")
                self.assertEqual(result["confidence_level"], "observational")

    def test_prompt_templates_format_and_explain_evidence_limit(self):
        for name in ("research_candidates_prompt.txt", "research_score_prompt.txt", "longform_research_prompt.txt",
                     "script_prompt.txt", "longform_script_prompt.txt"):
            text = (ROOT / "prompts" / name).read_text()
            fields = {field for _, field, _, _ in Formatter().parse(text) if field}
            formatted = text.format(**{field: "fixture" for field in fields})
            self.assertTrue(formatted)
            self.assertIn("do not need citations", text)

    def test_flagged_factual_short_cannot_be_selected(self):
        candidate = {"topic": "Dopamine statistics", "content_basis": "factual_claim"}
        result = short._fallback_score_candidate(candidate, 1)
        self.assertEqual(result["evidence_status"], "unverified")
        self.assertEqual(result["safety_brand_score"], 1)
        self.assertEqual(result["total_score"], 0)

    def test_flagged_factual_long_topic_stops_without_paid_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {"research_model": "test", "topic_memory_file": str(Path(directory) / "topics.json")}
            with patch.object(long, "_generate_longform_topic", return_value={"topic": "Dopamine statistics", "content_basis": "factual_claim"}):
                with self.assertRaisesRegex(RuntimeError, "factual verification"):
                    long.run_longform_research("test", directory, config)


if __name__ == "__main__":
    unittest.main()
