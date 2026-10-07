from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from modules.image_gen import _build_pools
from modules.longform_video_assembler import _queries_for_beat, _queries_for_chapter


class ClipSearchRegressionTests(unittest.TestCase):
    def memory(self, count):
        return [{"provider": "pexels", "provider_id": str(index),
                 "used_at": datetime.now(timezone.utc).isoformat()} for index in range(count)]

    def test_blocked_first_page_still_searches_alternates(self):
        blocked = [{"provider_id": str(index)} for index in range(20)]
        fresh = [{"provider_id": "fresh"}]
        with patch("modules.image_gen._query_alternates", return_value=["primary", "alternate", "third"]), patch("modules.image_gen._pexels_candidates", side_effect=[blocked, fresh, []]) as search:
            pools = _build_pools([{"id": 1, "pexels_query": "primary"}], self.memory(20), {})
        self.assertEqual(search.call_count, 3)
        self.assertEqual(pools[1], fresh)

    def test_enough_eligible_results_do_not_add_search_calls(self):
        eligible = [{"provider_id": f"fresh-{index}"} for index in range(12)]
        with patch("modules.image_gen._query_alternates", return_value=["primary", "alternate"]), patch("modules.image_gen._pexels_candidates", return_value=eligible) as search:
            pools = _build_pools([{"id": 1, "pexels_query": "primary"}], [], {})
        search.assert_called_once()
        self.assertEqual(len(pools[1]), 12)

    def test_overlapping_results_count_unique_eligible_ids_and_share_cache(self):
        first = [{"provider_id": str(index)} for index in range(12)]
        second = [{"provider_id": f"fresh-{index}"} for index in range(10)]
        with patch("modules.image_gen._query_alternates", return_value=["primary", "alternate"]), patch("modules.image_gen._pexels_candidates", side_effect=[first, second]) as search:
            pools = _build_pools([{"id": 1, "pexels_query": "primary"}, {"id": 2, "pexels_query": "primary"}], self.memory(10), {})
        self.assertEqual(search.call_count, 2)
        self.assertEqual(len(pools[1]), 12)
        self.assertEqual(pools[1], pools[2])
        self.assertFalse({str(index) for index in range(10)} & {item["provider_id"] for item in pools[1]})

    def test_beat_number_does_not_choose_another_chapters_brief(self):
        script = {"visual_brief": [
            {"chapter_id": 1, "stock_queries": ["hands holding letter"]},
            {"chapter_id": 2, "stock_queries": ["two people talking"]}]}
        for beat_id in (2, 8, 19):
            beat = {"id": beat_id, "chapter_id": 1, "voiceover": "Waiting.", "label": "opening"}
            self.assertEqual(_queries_for_beat(script, beat, {}, beat_id - 1), ["hands holding letter"])

    def test_direct_chapter_lookup_still_uses_its_id(self):
        script = {"visual_brief": [{"chapter_id": 2, "stock_queries": ["two people talking"]}]}
        self.assertEqual(_queries_for_chapter(script, {"id": 2}, {}, 0), ["two people talking"])

    def test_specific_direction_precedes_generic_keyword_matches(self):
        specific = ["person placing phone face down", "person walking outside daylight"]
        script = {"visual_brief": [{"chapter_id": 1, "stock_queries": specific}]}
        beat = {"id": 1, "chapter_id": 1, "voiceover": "You put your phone down and walk outside. You finally feel calm."}
        queries = _queries_for_beat(script, beat, {}, 0)
        self.assertEqual(queries[:2], specific)
        self.assertEqual(queries[2], "phone screen bed")
        self.assertEqual(len(queries), 5)

    def test_missing_brief_preserves_keyword_fallback(self):
        queries = _queries_for_beat({}, {"id": 1, "voiceover": "A phone message."}, {}, 0)
        self.assertEqual(queries, ["phone screen bed", "person looking at phone", "phone screen night",
                                   "rainy apartment window", "city night walking"])

    def test_no_keywords_or_brief_uses_general_fallback(self):
        queries = _queries_for_beat({}, {"id": 1, "voiceover": "Waiting."}, {}, 0)
        self.assertEqual(queries, ["rainy apartment window", "city night walking", "candlelit room"])

    def test_specific_and_keyword_queries_are_deduplicated(self):
        script = {"visual_brief": [{"chapter_id": 1, "stock_queries": ["phone screen bed", "phone screen bed"]}]}
        queries = _queries_for_beat(script, {"chapter_id": 1, "voiceover": "phone"}, {}, 0)
        self.assertEqual(queries, ["phone screen bed", "person looking at phone", "phone screen night"])


if __name__ == "__main__":
    unittest.main()
