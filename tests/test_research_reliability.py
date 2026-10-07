import json
from pathlib import Path
from string import Formatter
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from modules import research_agent as short
from modules import longform_research_agent as long
from utils.research_evidence import normalize_research_basis


ROOT = Path(__file__).resolve().parents[1]
PARTS = ("audience_fit_score", "emotional_tension_score", "scriptability_score",
         "share_save_score", "safety_brand_score")


class ResearchReliabilityTests(unittest.TestCase):
    def test_fallback_does_not_inherit_inflated_model_scores(self):
        candidate = {"topic": "Communication", "emotional_trigger": "feeling bad",
                     **{key: 4 for key in PARTS}}
        result = short._fallback_score_candidate(candidate)
        self.assertEqual(result["total_score"], sum(result[key] for key in PARTS))
        self.assertEqual(result["total_score"], 11)
        self.assertEqual(result["scoring_source"], "deterministic_fallback")

    def test_fallback_applies_repeat_penalties_once(self):
        result = short._fallback_score_candidate({"topic": "Communication", "angle_warning": True,
                                                  "category_recent_warning": True})
        self.assertEqual(result["total_score"], sum(result[key] for key in PARTS) - 2)

    def test_source_pool_is_balanced_and_has_no_fake_verification(self):
        signals = {source: [f"{source} title {i}" for i in range(40)]
                   for source in ("pytrends", "youtube", "reddit")}
        signals["window_days"] = 30
        context = short._signal_context(signals)
        presented = context["signals_presented"]
        self.assertEqual(len(presented), 30)
        for source in ("pytrends", "youtube", "reddit"):
            self.assertEqual(sum(x["source"] == source for x in presented), 10)
        self.assertEqual(context["window_days"], 30)
        self.assertEqual(context["claim_verification"], "none")

    def test_source_duplicates_are_removed_and_empty_sources_do_not_waste_slots(self):
        context = short._signal_context({"pytrends": ["same", "same"], "youtube": ["SAME", "other"]})
        self.assertEqual([x["text"] for x in context["signals_presented"]], ["same", "other"])
        self.assertEqual(short._signal_context({})["mode"], "evergreen_ideation")

    def test_candidate_provenance_and_evergreen_instruction(self):
        with patch.object(short, "_assert_gemini_key"), patch.object(short, "weekly_direction_prompt", return_value=""), \
             patch.object(short, "generate_json", return_value=[{"topic": "A quiet message"}]) as model:
            result = short._generate_candidates.__wrapped__({}, [], [], [], {}, "test")
        self.assertIn("EVERGREEN MODE", model.call_args.args[0])
        self.assertEqual(result[0]["topic_origin"], "evergreen_ideation")
        scored = short._fallback_score_candidate(result[0])
        self.assertEqual(scored["research_context"]["claim_verification"], "none")
        self.assertEqual(scored["topic_origin"], "evergreen_ideation")

    def test_obvious_factual_claim_cannot_hide_under_emotional_label(self):
        for claim in ("Research proves 90% of people do this because of dopamine.",
                      "Your nervous system learned to mistake uncertainty for love."):
            with self.subTest(claim=claim):
                candidate = {"topic": "A familiar pattern", "core_claim": claim,
                             "content_basis": "emotional_observation"}
                self.assertEqual(normalize_research_basis(candidate)["evidence_status"], "unverified")
                self.assertEqual(short._fallback_score_candidate(candidate)["total_score"], 0)
                rewritten_score = {"topic": candidate["topic"], **{key: 4 for key in PARTS}}
                self.assertEqual(short._finalize_candidate_score(candidate, rewritten_score)["total_score"], 0)

    def test_emotional_scene_still_needs_no_citation(self):
        result = normalize_research_basis({"core_claim": "A steady reply can feel unfamiliar after weeks of waiting."})
        self.assertEqual(result["evidence_status"], "not_required")

    def test_final_short_file_preserves_origin_and_source_inputs(self):
        for origin in ("signal_informed_ideation", "evergreen_fallback"):
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as directory:
                context = {"mode": origin, "claim_verification": "none",
                           "signals_presented": [{"source": "reddit", "text": "An illustrative title"}]
                           if origin == "signal_informed_ideation" else []}
                candidate = {"topic": "Checking a message in bed", "topic_origin": origin,
                             "research_context": context, "content_basis": "emotional_observation"}
                config = {"research_model": "test", "duplicate_similarity_threshold": 0.78,
                          "topic_memory_lookback_days": 90, "topic_memory_file": str(Path(directory) / "memory.json")}
                with patch.object(short, "_harvest_signals", return_value={}), \
                     patch.object(short, "_generate_candidates", return_value=[dict(candidate) for _ in range(3)]), \
                     patch.object(short, "_filter_candidates", side_effect=lambda pool, *args: pool), \
                     patch.object(short, "_score_candidates_parallel", return_value=[]):
                    short.run_research("test", directory, config)
                saved = json.loads((Path(directory) / "01_research.json").read_text())
                self.assertEqual(saved["topic_origin"], origin)
                self.assertEqual(saved["research_context"], context)
                self.assertEqual(saved["total_score"], 11)

    def test_partial_trends_failure_retains_related_queries(self):
        frame = MagicMock()
        frame.empty = False
        frame.__getitem__.return_value.tolist.return_value = ["relationship query"]
        client = MagicMock()
        client.related_queries.return_value = {"relationship": {"rising": frame}}
        client.trending_searches.side_effect = RuntimeError("unavailable")
        with patch.object(short, "TrendReq", return_value=client):
            self.assertEqual(short._harvest_pytrends(), ["relationship query"])

    def test_thirty_day_expansion_changes_youtube_window(self):
        with patch.object(short, "_harvest_youtube", return_value=[]) as fetch:
            result = short._harvest_signals("now 30-d", {"research_signal_sources": ["youtube"]})
        fetch.assert_called_once_with(days=30)
        self.assertEqual(result["window_days"], 30)

    def test_long_fallback_rejects_exhausted_pool_and_records_actual_reason(self):
        topics = long._fallback_longform_topics()
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / "topics.json"
            memory.write_text(json.dumps([{"topic": x["topic"]} for x in topics]))
            with self.assertRaisesRegex(RuntimeError, "refusing a repeated topic"):
                long._fallback_longform_topic(str(memory))
            memory.write_text("[]")
            result = long._fallback_longform_topic(str(memory), "primary topic duplicated a recent topic")
        self.assertEqual(result["topic_origin"], "evergreen_fallback")
        self.assertIn("duplicated", result["research_fallback_reason"])
        for item in topics:
            self.assertEqual(normalize_research_basis(item)["evidence_status"], "not_required")

    def test_research_prompts_keep_template_contract_and_story_guidance(self):
        for name in ("research_candidates_prompt.txt", "research_score_prompt.txt", "longform_research_prompt.txt"):
            text = (ROOT / "prompts" / name).read_text()
            fields = {field for _, field, _, _ in Formatter().parse(text) if field}
            self.assertTrue(text.format(**{field: "fixture" for field in fields}))
            self.assertNotIn("this video will prove", text)
            self.assertNotIn("hope with someone else's face", text)
        candidate_prompt = (ROOT / "prompts/research_candidates_prompt.txt").read_text()
        self.assertIn("choice", candidate_prompt)
        self.assertIn("earned payoff", candidate_prompt)
        self.assertNotIn("- psychology_drop:", candidate_prompt)


if __name__ == "__main__":
    unittest.main()
