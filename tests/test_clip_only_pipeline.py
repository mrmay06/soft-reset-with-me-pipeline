from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from modules.image_gen import _assign_globally, _hash_distance
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
