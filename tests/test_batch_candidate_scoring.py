import unittest
from unittest.mock import patch

from modules import research_agent as research


class BatchScoringTests(unittest.TestCase):
    def candidates(self):
        return [{"topic": f"Checking message {index}", "category": "dating", "angle_type": "reframe",
                 "emotional_trigger": "typing a message in bed at night then deleting it",
                 "editorial_seed": "Editing can help you communicate but can also hide what you actually meant.",
                 "only_soft_reset_line": "The edit should not erase what you meant.",
                 "content_format": "specific_scenario", "content_basis": "emotional_observation",
                 "_candidate_rank": index} for index in (1, 2)]

    def results(self):
        return [{"candidate_id": index, "topic": candidate["topic"],
                 **{field: 4 for field in ("audience_fit_score", "emotional_tension_score", "scriptability_score", "share_save_score", "safety_brand_score")}}
                for index, candidate in enumerate(self.candidates(), 1)]

    def batch(self, candidates, raw):
        with patch.object(research, "_assert_gemini_key"), patch.object(research, "generate_json", return_value=raw) as model:
            result = research._score_candidate_batch.__wrapped__(candidates, "test")
        model.assert_called_once()
        return result

    def test_one_call_scores_pool_and_reorders_by_id(self):
        result = self.batch(self.candidates(), self.results()[::-1])
        self.assertEqual([item["topic"] for item in result], [item["topic"] for item in self.candidates()])
        self.assertEqual([item["total_score"] for item in result], [20, 20])
        self.assertTrue(all(item["scoring_source"] == "ai_batch" for item in result))

    def test_existing_local_safety_and_repeat_penalties_remain(self):
        candidates = self.candidates()
        candidates[0]["content_basis"] = "factual_claim"
        candidates[1].update(angle_warning=True, category_recent_warning=True)
        raw = self.results()
        raw[0]["content_basis"] = "emotional_observation"
        result = self.batch(candidates, raw)
        self.assertEqual(result[0]["total_score"], 0)
        self.assertEqual(result[0]["safety_brand_score"], 1)
        self.assertEqual(result[1]["total_score"], 18)

    def test_malformed_ids_counts_scores_and_identity_are_rejected(self):
        examples = [self.results()[:1], self.results() + self.results()[:1],
                    [self.results()[0], self.results()[0]],
                    [{**self.results()[0], "candidate_id": 99}, self.results()[1]],
                    [{**self.results()[0], "candidate_id": True}, self.results()[1]],
                    [{**self.results()[0], "audience_fit_score": 5}, self.results()[1]],
                    [{**self.results()[0], "safety_brand_score": "4"}, self.results()[1]],
                    [{**self.results()[0], "topic": "Different topic"}, self.results()[1]]]
        for raw in examples:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.batch(self.candidates(), raw)

    def test_empty_pool_uses_no_call_and_failure_keeps_existing_fallback_contract(self):
        with patch.object(research, "_score_candidate_batch", side_effect=RuntimeError("offline")) as batch:
            self.assertEqual(research._score_candidates_parallel([], "test"), [])
            batch.assert_not_called()
            self.assertEqual(research._score_candidates_parallel(self.candidates(), "test"), [])
            batch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
