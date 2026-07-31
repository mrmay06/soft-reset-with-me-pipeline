from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from modules.image_gen import _assign_globally, _hash_distance
from modules.creative_judge import _hard_failures
from modules.longform_audio_agent import _build_tts_chunks
from modules.longform_thumbnail_agent import _pick_thumbnail_frames
from modules.visual_director import _validate_manifest
from utils.weekly_direction import load_weekly_direction, weekly_direction_prompt
from utils.publish_schedule import youtube_publish_at


ROOT = Path(__file__).resolve().parents[1]


class SafetyConfigTests(unittest.TestCase):
    def test_both_tracks_are_paused_and_private(self):
        for relative in ("config/pipeline_config.json", "config/longform_config.json"):
            config = json.loads((ROOT / relative).read_text())
            self.assertFalse(config["automation_enabled"])
            self.assertFalse(config["public_release_enabled"])
            self.assertEqual(config["privacy_status"], "private")

    def test_release_schedule_uses_configured_et_times(self):
        now = datetime(2026, 7, 31, 10, 0, tzinfo=timezone.utc)
        short = youtube_publish_at(
            {"public_release_enabled": True, "timezone": "America/New_York", "target_publish_time_et": "20:00"},
            "shorts",
            now,
        )
        longform = youtube_publish_at(
            {"public_release_enabled": True, "timezone": "America/New_York", "target_publish_time_et": "12:00"},
            "longform",
            now,
        )
        self.assertEqual(short, "2026-08-01T00:00:00Z")
        self.assertEqual(longform, "2026-08-02T16:00:00Z")


class ClipSelectionTests(unittest.TestCase):
    def test_global_assignment_uses_unique_provider_ids(self):
        scenes = [{"id": 1}, {"id": 2}]
        shared = {"provider": "pexels", "provider_id": "1", "rank": 0, "creator": "a", "width": 1080, "height": 1920, "duration": 8}
        alternate = {"provider": "pexels", "provider_id": "2", "rank": 1, "creator": "b", "width": 1080, "height": 1920, "duration": 8}
        ranked = _assign_globally(scenes, {1: [shared, alternate], 2: [shared, alternate]}, [], {})
        self.assertEqual(ranked[1][0]["provider_id"], "1")
        self.assertEqual(ranked[2][0]["provider_id"], "2")

    def test_perceptual_hash_distance(self):
        self.assertEqual(_hash_distance("0000000000000000", "0000000000000000"), 0)
        self.assertEqual(_hash_distance("0000000000000000", "000000000000000f"), 4)

    def test_manifest_normalizes_legacy_image_response_to_video(self):
        manifest = {
            "thumbnail": {"image_prompt": "legacy"},
            "scenes": [{
                "id": 1,
                "covers_dialogue": "You already know.",
                "visual_type": "image",
                "image_prompt": "legacy generated still",
                "pexels_query": "person at window",
            }],
        }
        valid, error = _validate_manifest(manifest, "You already know.")
        self.assertTrue(valid, error)
        self.assertEqual(manifest["scenes"][0]["visual_type"], "video")
        self.assertIsNone(manifest["scenes"][0]["image_prompt"])
        self.assertEqual(manifest["thumbnail"], {"source": "selected_footage"})

    def test_soft_word_target_warning_is_not_a_hard_failure(self):
        config = {
            "longform_target_words_min": 260,
            "longform_target_words_max": 390,
            "longform_hard_words_min": 200,
            "longform_hard_words_max": 430,
            "creative_judge_min_composite": 5.5,
            "creative_judge_min_policy_risk": 7,
            "creative_judge_min_script_clarity": 6,
            "creative_judge_min_title_accuracy": 6,
        }
        raw = {
            "composite_score": 7,
            "scores": {
                "policy_factual_risk": {"score": 10},
                "script_clarity": {"score": 9},
                "title_accuracy": {"score": 9},
            },
        }
        self.assertEqual(_hard_failures(raw, {"word_count": 381, "validation": "forced"}, config), [])

    def test_long_tts_splits_only_at_chapter_boundaries(self):
        script = {"chapters": [
            {"voiceover": "one " * 120},
            {"voiceover": "two " * 120},
            {"voiceover": "three " * 80},
        ]}
        chunks = _build_tts_chunks(script, 220)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("one"))
        self.assertTrue(chunks[1].startswith("two"))

    def test_thumbnail_frames_use_semantic_source_queries(self):
        frames = [
            {"path": "object.jpg", "query": "quiet morning room", "score": 99},
            {"path": "person.jpg", "query": "woman sitting alone night", "score": 50},
            {"path": "release.jpg", "query": "open window curtains", "score": 40},
        ]
        face, left, right = _pick_thumbnail_frames(frames)
        self.assertEqual(face, "person.jpg")
        self.assertEqual(left, "person.jpg")
        self.assertEqual(right, "object.jpg")


class WeeklyDirectionTests(unittest.TestCase):
    def test_missing_or_inactive_direction_is_optional(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.json"
            self.assertEqual(load_weekly_direction(path), {})
            self.assertEqual(weekly_direction_prompt(path), "")
            path.write_text(json.dumps({"active": False, "priorities": ["breakups"]}))
            self.assertEqual(load_weekly_direction(path), {})

    def test_active_direction_becomes_soft_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "direction.json"
            path.write_text(json.dumps({"active": True, "priorities": ["boundaries"], "avoid": ["dating hacks"]}))
            prompt = weekly_direction_prompt(path)
            self.assertIn("Prioritize: boundaries", prompt)
            self.assertIn("Avoid: dating hacks", prompt)


if __name__ == "__main__":
    unittest.main()
