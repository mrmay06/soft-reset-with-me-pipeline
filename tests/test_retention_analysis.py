import json
import os
import string
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from modules import logger
from tools import strategy_reviewer, weekly_analytics_fetch, weekly_preprocess
from utils import retention_analysis as ra
from utils import spoken_timeline as st


ROOT = Path(__file__).resolve().parents[1]

TIMELINE = {
    "version": 1,
    "source": "captions",
    "duration_sec": 40.0,
    "voice_end_sec": 36.0,
    "lines": [
        {"start": 0.0, "section": "hook", "text": "Three honest sentences, typed."},
        {"start": 3.3, "section": "hook", "text": "You hold backspace until they're gone."},
        {"start": 11.0, "section": "tension", "text": "But the hurt is still there an hour later."},
        {"start": 21.0, "section": "insight", "text": "Deciding it doesn't matter is one thing."},
        {"start": 31.0, "section": "loopback", "text": "Try one sentence instead of three."},
    ],
}


def curve(duration=40.0, opening=1.3, cliff_at=None, cliff_drop=0.0, hook_loss=0.3, noise=0.0):
    """101 points: loop-inflated opening, hook loss over 3s, gentle slide, optional sharp cliff."""
    points = []
    for i in range(101):
        ratio = i / 100
        t = ratio * duration
        value = opening - hook_loss * min(t, 3.0) / 3.0 - 0.005 * max(0.0, t - 3.0)
        if cliff_at is not None and t >= cliff_at:
            value -= cliff_drop
        value += noise if i % 2 else -noise
        points.append([ratio, round(value, 4), 0.6])
    return points


class RetentionCurveAnalysisTests(unittest.TestCase):
    def test_parse_curve_rows_sorts_and_tolerates_missing_relative_metric(self):
        response = {
            "columnHeaders": [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"}],
            "rows": [[0.5, 0.8], [0.0, 1.2], ["bad", 1], [1.0, 0.6]],
        }
        self.assertEqual(ra.parse_curve_rows(response), [[0.0, 1.2, None], [0.5, 0.8, None], [1.0, 0.6, None]])
        self.assertEqual(ra.parse_curve_rows({"columnHeaders": [{"name": "views"}], "rows": [[1]]}), [])
        self.assertEqual(ra.parse_curve_rows({}), [])

    def test_hook_leak_is_relative_to_loop_inflated_opening(self):
        result = ra.analyze_curve(curve(opening=1.3, hook_loss=0.39), 40.0, TIMELINE, views=5000)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["loop_inflated"])
        self.assertEqual(result["opening_watch_ratio"], 1.3)
        self.assertAlmostEqual(result["hook_leak_pct"], 30.0, delta=1.5)
        self.assertEqual(result["confidence"], "normal")
        self.assertEqual(result["line_at_hook_end"], "Three honest sentences, typed.")

    def test_hook_window_is_configurable(self):
        short_window = ra.analyze_curve(curve(), 40.0, TIMELINE, hook_window_sec=1.5)
        self.assertEqual(short_window["hook_window_sec"], 1.5)
        self.assertLess(short_window["hook_leak_pct"], ra.analyze_curve(curve(), 40.0, TIMELINE)["hook_leak_pct"])

    def test_cliff_maps_to_spoken_line_and_noise_is_ignored(self):
        result = ra.analyze_curve(curve(cliff_at=22.0, cliff_drop=0.2, noise=0.004), 40.0, TIMELINE, views=300)
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(len(result["cliffs"]), 1)
        cliff = result["cliffs"][0]
        self.assertTrue(21.0 <= cliff["at_sec"] <= 23.0)
        self.assertEqual(cliff["section"], "insight")
        self.assertEqual(cliff["line"], "Deciding it doesn't matter is one thing.")
        self.assertGreater(cliff["drop_pct"], 10)

    def test_cliff_after_voice_is_marked_as_ending_tail(self):
        result = ra.analyze_curve(curve(cliff_at=38.0, cliff_drop=0.2), 40.0, TIMELINE)
        self.assertEqual(result["cliffs"][0]["section"], "ending_tail")
        self.assertEqual(result["cliffs"][0]["line"], ra.AFTER_VOICE_LABEL)

    def test_slide_and_end_retention(self):
        result = ra.analyze_curve(curve(opening=1.0, hook_loss=0.2), 40.0)
        # 0.005 per second over the 3s..36s mid window = 5% of opening per 10s.
        self.assertAlmostEqual(result["mid_slide_pct_per_10s"], 5.0, delta=0.4)
        self.assertAlmostEqual(result["end_retention_pct_of_opening"], 61.5, delta=0.5)
        self.assertEqual(result["avg_relative_retention"], 0.6)
        self.assertNotIn("line_at_hook_end", result)

    def test_insufficient_data_never_raises(self):
        self.assertEqual(ra.analyze_curve(curve(), 0)["status"], "insufficient_data")
        self.assertEqual(ra.analyze_curve([[0, 1, None]], 30)["status"], "insufficient_data")
        self.assertEqual(ra.analyze_curve([[0, 0, None], [0.5, 0, None], [1, 0, None]], 30)["status"], "insufficient_data")

    def test_aggregate_patterns_counts_sections_and_confidence(self):
        analyses = [
            ra.analyze_curve(curve(cliff_at=22.0, cliff_drop=0.2), 40.0, TIMELINE, views=5000),
            ra.analyze_curve(curve(cliff_at=25.0, cliff_drop=0.2), 40.0, TIMELINE, views=100),
            {"status": "insufficient_data"},
        ]
        patterns = ra.aggregate_patterns(analyses)
        self.assertEqual(patterns["videos_with_curves"], 2)
        self.assertEqual(patterns["videos_normal_confidence"], 1)
        self.assertEqual(patterns["cliff_count_by_section"], {"insight": 2})
        self.assertEqual(ra.aggregate_patterns([]), {"videos_with_curves": 0})


class SpokenTimelineTests(unittest.TestCase):
    SCRIPT = {
        "hook": "Three honest sentences, typed. You hold backspace.",
        "tension": "It was never the feeling.",
        "insight": "",
        "loopback": "Try one sentence.",
        "like_cta": "",
    }

    def write_run(self, base: Path, words: list[tuple[str, float, float]] | None, render=True):
        if words is not None:
            lines = ["[Events]"] + [
                f"Dialogue: 0,0:00:{int(s):02d}.{int(round(s % 1 * 100)):02d},0:00:{int(e):02d}.{int(round(e % 1 * 100)):02d},Default,,0,0,0,,{w}"
                for w, s, e in words
            ]
            (base / "04_captions.ass").write_text("\n".join(lines))
        (base / "03_voice_meta.json").write_text(json.dumps({"duration_sec": 12.0}))
        if render:
            (base / "06_render_meta.json").write_text(json.dumps({"final_duration_sec": 15.5, "voice_duration_sec": 12.0}))

    def test_caption_timing_aligns_script_sentences_despite_asr_differences(self):
        words = [("Honest", 0.3, 0.8), ("Sentences", 0.8, 1.2), ("Typed.", 1.2, 1.9),
                 ("You", 2.5, 2.7), ("Hold", 2.7, 3.0), ("Back", 3.0, 3.2), ("Space.", 3.2, 3.6),
                 ("It", 4.1, 4.3), ("Was", 4.3, 4.5), ("Never", 4.5, 4.9), ("The", 4.9, 5.0), ("Feeling.", 5.0, 5.6),
                 ("Try", 9.0, 9.3), ("One", 9.3, 9.5), ("Sentence.", 9.5, 10.2)]
        with tempfile.TemporaryDirectory() as tmp:
            self.write_run(Path(tmp), words)
            timeline = st.build_spoken_timeline(tmp, self.SCRIPT)
        self.assertEqual(timeline["source"], "captions")
        self.assertEqual(timeline["duration_sec"], 15.5)
        self.assertEqual(timeline["voice_end_sec"], 10.2)
        self.assertEqual([line["start"] for line in timeline["lines"]], [0.3, 2.5, 4.1, 9.0])
        self.assertEqual([line["section"] for line in timeline["lines"]], ["hook", "hook", "tension", "loopback"])
        self.assertEqual(timeline["lines"][0]["text"], "Three honest sentences, typed.")

    def test_estimated_timeline_without_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.write_run(Path(tmp), None, render=False)
            timeline = st.build_spoken_timeline(tmp, self.SCRIPT)
        self.assertEqual(timeline["source"], "estimated")
        self.assertEqual(timeline["duration_sec"], 12.0)
        self.assertEqual(timeline["lines"][0]["start"], 0.0)
        starts = [line["start"] for line in timeline["lines"]]
        self.assertEqual(starts, sorted(starts))

    def test_empty_run_dir_yields_empty_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(st.build_spoken_timeline(tmp, self.SCRIPT), {})
            self.assertEqual(st.build_spoken_timeline(tmp, {}), {})

    def test_logger_stores_timeline_and_survives_timeline_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            files = {
                "01_research.json": {"topic": "t", "category": "c", "total_score": 18, "source_name": "s"},
                "02_script.json": self.SCRIPT,
                "07_metadata.json": {"title": "Title"},
                "03_asset_meta.json": {"fallback_count": 0},
                "08_upload_meta.json": {"youtube_video_id": "yt1", "youtube_url": "u"},
            }
            for name, data in files.items():
                (run_dir / name).write_text(json.dumps(data))
            self.write_run(run_dir, [("Three", 0.0, 0.4), ("Try", 9.0, 9.4)])
            config = {"topic_memory_file": str(run_dir / "memory.json")}
            entry = logger.run_logger("vid1", tmp, config)
            self.assertEqual(entry["spoken_timeline"]["source"], "captions")
            stored = json.loads((run_dir / "memory.json").read_text())
            self.assertEqual(stored[0]["spoken_timeline"]["duration_sec"], 15.5)
            self.assertLess(len(json.dumps(stored[0]["spoken_timeline"])), 1500)

            with patch.object(logger, "build_spoken_timeline", side_effect=ValueError("boom")):
                entry = logger.run_logger("vid2", tmp, config)
            self.assertEqual(entry["spoken_timeline"], {})


class FakeQuery:
    def __init__(self, fail):
        self.fail = fail

    def execute(self):
        if self.fail:
            raise RuntimeError("quota")
        return {
            "columnHeaders": [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"},
                              {"name": "relativeRetentionPerformance"}],
            "rows": [[p[0], p[1], p[2]] for p in curve()],
        }


class FakeAnalytics:
    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.curve_requests = []

    def reports(self):
        return self

    def query(self, **kwargs):
        video = kwargs["filters"].split("==", 1)[1]
        self.curve_requests.append(video)
        return FakeQuery(video in self.fail_for)


class WeeklyRetentionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_fetch_requests_curves_only_for_eligible_videos_and_soft_fails(self):
        published = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        memory = [
            {"video_id": v, "youtube_video_id": f"yt_{v}", "published_date": published, "title": v,
             "spoken_timeline": TIMELINE if v == "a" else {}}
            for v in ("a", "b", "c")
        ]
        memory_path = self.base / "memory.json"
        memory_path.write_text(json.dumps(memory))
        views = {"yt_a": 900, "yt_b": 10, "yt_c": 700}
        analytics = FakeAnalytics(fail_for={"yt_c"})
        with patch.object(weekly_analytics_fetch, "ANALYTICS_CACHE_DIR", str(self.base / "cache")), \
                patch.object(weekly_analytics_fetch, "_memory_sources",
                             return_value=[(str(memory_path), "shorts", {"performance_min_views": 50})]), \
                patch.object(weekly_analytics_fetch, "_get_youtube_client", return_value=(None, analytics)), \
                patch.object(weekly_analytics_fetch, "_get_channel_id", return_value="chan"), \
                patch.object(weekly_analytics_fetch, "_get_judge_report", return_value={}), \
                patch.object(weekly_analytics_fetch, "_fetch_video_analytics",
                             side_effect=lambda _c, yt, _ch: {"views": views[yt], "averageViewPercentage": 80}):
            path = weekly_analytics_fetch.run_fetch(week_label="2026-W40")
        cache = json.loads(Path(path).read_text())
        by_id = {v["youtube_video_id"]: v for v in cache["videos"]}
        self.assertEqual(analytics.curve_requests, ["yt_a", "yt_c"])
        self.assertEqual(len(by_id["yt_a"]["retention_curve"]), 101)
        self.assertIsNone(by_id["yt_b"]["retention_curve"])
        self.assertIsNone(by_id["yt_c"]["retention_curve"])
        self.assertEqual(by_id["yt_a"]["spoken_timeline"], TIMELINE)
        self.assertEqual(cache["retention_curves_fetched"], 1)

    def test_preprocess_emits_retention_insights_and_performer_summaries(self):
        published = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        videos = []
        for index, views in enumerate([5000, 3000, 200, 150]):
            videos.append({
                "youtube_video_id": f"yt{index}", "video_id": f"v{index}", "title": f"Video {index}",
                "published_at": published, "track": "shorts", "traits": {},
                "analytics": {"views": views, "averageViewPercentage": 70 + index,
                              "averageViewDuration": 28, "excluded_from_strategy": False},
                "retention_curve": curve(cliff_at=22.0, cliff_drop=0.2) if index != 3 else None,
                # Video 1 has no stored timeline, so duration comes from YouTube's averages.
                "spoken_timeline": TIMELINE if index != 1 else {},
            })
        cache_dir = self.base / "cache"
        cache_dir.mkdir()
        (cache_dir / "2026-W40.json").write_text(json.dumps({"videos": videos}))
        (self.base / "config.json").write_text(json.dumps({"retention_hook_window_sec": 2.5, "retention_noisy_views": 1000}))
        with patch.object(weekly_preprocess, "ANALYTICS_CACHE_DIR", str(cache_dir)), \
                patch.object(weekly_preprocess, "COMPARISONS_DIR", str(self.base / "cmp")), \
                patch.object(weekly_preprocess, "STRATEGY_FILE", str(self.base / "missing.json")), \
                patch.object(weekly_preprocess, "PIPELINE_CONFIG_FILE", str(self.base / "config.json")):
            path = weekly_preprocess.run_preprocess(week_label="2026-W40")
        output = json.loads(Path(path).read_text())
        insights = output["retention_insights"]
        self.assertEqual(insights["settings"]["hook_window_sec"], 2.5)
        self.assertEqual(insights["patterns"]["videos_with_curves"], 3)
        self.assertEqual(insights["patterns"]["videos_normal_confidence"], 2)
        self.assertEqual([v["views"] for v in insights["videos"]], [5000, 3000, 200])
        self.assertEqual(insights["videos"][0]["cliffs"][0]["section"], "insight")
        self.assertEqual(insights["videos"][1]["timeline_source"], "missing")
        self.assertNotIn("line", insights["videos"][1]["cliffs"][0])
        self.assertEqual(insights["videos"][2]["confidence"], "low")
        summaries = [p["retention_curve"] for p in output["top_performers"] + output["bottom_performers"]]
        self.assertTrue(any(s and s["hook_leak_pct"] > 0 for s in summaries))

    def test_video_duration_falls_back_to_youtube_averages(self):
        video = {"analytics": {"averageViewDuration": 30, "averageViewPercentage": 75}}
        self.assertEqual(weekly_preprocess._video_duration(video), 40.0)
        self.assertIsNone(weekly_preprocess._video_duration({"analytics": {}}))

    def test_weekly_prompt_has_retention_slot_and_noise_warning(self):
        template = (ROOT / "prompts" / "weekly_analysis_prompt.txt").read_text()
        fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
        self.assertIn("retention_insights", fields)
        self.assertIn("noisy", template)
        template.format(**{name: "x" for name in fields})

    def test_reviewer_prompt_keeps_retention_out_of_truncated_comparison(self):
        comparison = {"retention_insights": {"patterns": {"videos_with_curves": 3}}, "comparisons_by_trait": {"a": 1}}
        prompt = strategy_reviewer._review_prompt({}, comparison, {})
        self.assertIn('"videos_with_curves":3', prompt)
        self.assertEqual(prompt.count("videos_with_curves"), 1)


if __name__ == "__main__":
    unittest.main()
