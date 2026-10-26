import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from modules import research_agent as research

PARTS = ("audience_fit_score", "emotional_tension_score", "scriptability_score",
         "share_save_score", "safety_brand_score")


def _quiet(fn, *args, **kwargs):
    out = io.StringIO()
    with redirect_stdout(out):
        result = fn(*args, **kwargs)
    return result, out.getvalue()


class SignalLoggingTests(unittest.TestCase):
    def test_pytrends_uses_all_categories_and_skips_dead_trending_call(self):
        client = MagicMock()
        client.related_queries.return_value = {}
        with patch.object(research, "TrendReq", return_value=client):
            result, log = _quiet(research._harvest_pytrends)
        self.assertEqual(result, [])
        self.assertEqual(client.build_payload.call_args.kwargs["cat"], 0)
        client.trending_searches.assert_not_called()
        self.assertIn("no rising related queries", log)

    def test_pytrends_rate_limit_is_named(self):
        with patch.object(research, "TrendReq", side_effect=RuntimeError("Google returned a response with code 429")):
            result, log = _quiet(research._harvest_pytrends)
        self.assertEqual(result, [])
        self.assertIn("FAILED, rate-limited by Google (429)", log)

    def test_reddit_block_is_reported_not_silently_zero(self):
        blocked = MagicMock(status_code=403)
        with patch.object(research.requests, "get", return_value=blocked):
            result, log = _quiet(research._harvest_reddit, ["BreakUps", "self"])
        self.assertEqual(result, [])
        self.assertIn("2/2 subreddits FAILED (HTTP 403 on r/BreakUps, r/self)", log)
        self.assertIn("Reddit API app is needed", log)

    def test_signal_summary_warns_when_sources_are_empty(self):
        with patch.object(research, "_harvest_pytrends", return_value=[]), \
             patch.object(research, "_harvest_youtube", return_value=["a title"]), \
             patch.object(research, "_harvest_reddit", return_value=[]):
            _, log = _quiet(research._harvest_signals, "now 7-d", {})
        self.assertIn("youtube=1, pytrends=0, reddit=0", log)
        self.assertIn("pytrends, reddit returned nothing", log)


class CategoryPenaltyTests(unittest.TestCase):
    history = ["healing arcs", "self-worth shifts", "healing arcs", "relationship patterns",
               "conversation truths", "psychology drops"]

    def test_penalty_is_graded_by_use_and_recency(self):
        self.assertEqual(research._category_penalty("healing arcs", self.history), 3)
        self.assertEqual(research._category_penalty("self-worth shifts", self.history), 1)
        self.assertEqual(research._category_penalty("identity and growth", self.history), 0)

    def test_history_is_most_recent_first_with_repeats(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = Path(directory) / "memory.json"
            memory.write_text(json.dumps([
                {"published_date": "2026-10-01", "category": "Healing Arcs"},
                {"published_date": "2026-10-03", "category": "self-worth shifts"},
                {"published_date": "2026-10-02", "category": "healing arcs"},
            ]))
            self.assertEqual(research._load_category_history(str(memory), 6),
                             ["self-worth shifts", "healing arcs", "healing arcs"])

    def test_unused_category_now_beats_an_overused_one(self):
        candidates = [{"topic": "Overused category topic", "category": "healing arcs"},
                      {"topic": "Fresh category topic", "category": "identity and growth"}]
        filtered, _ = _quiet(research._filter_candidates, candidates, [], [], ["healing arcs"], [], [], [], 0.9,
                             self.history)
        scored = [research._finalize_candidate_score(c, {"topic": c["topic"], **{k: 4 for k in PARTS}})
                  for c in filtered]
        self.assertEqual(scored[1]["total_score"] - scored[0]["total_score"], 3)
        self.assertEqual(scored[0]["category_penalty"], 3)
        winner, _ = _quiet(research._pick_winner, scored)
        self.assertEqual(winner["topic"], "Fresh category topic")


class ComparativeRankTests(unittest.TestCase):
    def candidates(self, n=3):
        return [{"topic": f"Topic {i}", "category": "dating", "angle_type": "reframe",
                 "emotional_trigger": "typing a message in bed at night then deleting it",
                 "editorial_seed": "Editing can help you communicate but can also hide what you actually meant.",
                 "only_soft_reset_line": "The edit should not erase what you meant.",
                 "content_format": "specific_scenario", "content_basis": "emotional_observation",
                 "_candidate_rank": i} for i in range(1, n + 1)]

    def raw(self, ranks, scores=None):
        scores = scores or [4] * len(ranks)
        return [{"candidate_id": i, "topic": f"Topic {i}", "pool_rank": rank, "rank_reason": "why",
                 **{k: (scores[i - 1] if k == "share_save_score" else 4) for k in PARTS}}
                for i, rank in enumerate(ranks, 1)]

    def batch(self, raw, n=3):
        with patch.object(research, "_assert_gemini_key"), patch.object(research, "generate_json", return_value=raw) as model:
            result = research._score_candidate_batch.__wrapped__(self.candidates(n), "test")
        self.assertIn("pool_rank", model.call_args.args[0])
        return result

    def test_rank_breaks_ties_the_rubric_cannot(self):
        scored = self.batch(self.raw([3, 1, 2]))
        self.assertEqual([s["total_score"] for s in scored], [20, 20, 20])
        winner, log = _quiet(research._pick_winner, scored)
        self.assertEqual(winner["topic"], "Topic 2")
        self.assertIn("rank 1/3", log)

    def test_rank_can_overturn_one_point_but_not_three(self):
        one_point = self.batch(self.raw([3, 1, 2], scores=[4, 3, 3]))
        self.assertEqual(_quiet(research._pick_winner, one_point)[0]["topic"], "Topic 2")
        three_points = self.batch(self.raw([3, 1, 2], scores=[4, 1, 1]))
        for item in three_points[1:]:
            item["total_score"] -= 2
        self.assertEqual(_quiet(research._pick_winner, three_points)[0]["topic"], "Topic 1")

    def test_malformed_ranks_are_dropped_without_failing_scoring(self):
        scored = self.batch(self.raw([1, 1, 2]))
        self.assertTrue(all("pool_rank" not in s and "pool_size" not in s for s in scored))
        self.assertEqual(research._rank_bonus(scored[0]), 0.0)


if __name__ == "__main__":
    unittest.main()
