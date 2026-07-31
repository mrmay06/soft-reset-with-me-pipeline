from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

from modules.image_gen import _assign_globally, _hash_distance
from modules.creative_judge import _hard_failures, _script_evidence, run_creative_judge
from modules.longform_thumbnail_agent import _pick_thumbnail_frames, _select_primary_variant, _variant_copy
from modules.longform_video_assembler import _planned_final_duration
from modules.longform_script_agent import _blocking_script_issues, _validate_script as validate_longform_script
from modules.script_agent import _validate_script as validate_short_script
from modules.visual_director import _validate_manifest
from main_long import _enforce_longform_script_gate
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

    def test_research_grounded_duration_configuration(self):
        shorts = json.loads((ROOT / "config/pipeline_config.json").read_text())
        longform = json.loads((ROOT / "config/longform_config.json").read_text())
        self.assertEqual(
            (shorts["script_min_words"], shorts["script_max_words"]),
            (60, 90),
        )
        self.assertEqual(
            (shorts["script_hard_min_words"], shorts["script_hard_max_words"]),
            (45, 110),
        )
        self.assertEqual(
            (longform["longform_target_words_min"], longform["longform_target_words_max"]),
            (700, 950),
        )
        self.assertEqual(
            (longform["longform_hard_words_min"], longform["longform_hard_words_max"]),
            (600, 1100),
        )
        self.assertEqual(longform["longform_duration_label"], "4.5-6.5 minute")


class ScriptGuardrailTests(unittest.TestCase):
    def test_short_rejects_generic_callout_cta(self):
        config = json.loads((ROOT / "config/pipeline_config.json").read_text())
        script = {
            "editorial_pov": "Editing every honest message can quietly turn connection into a performance you must maintain.",
            "only_soft_reset_line": "You were not asking for too much; you were deleting the evidence.",
            "hook": "You type the honest message, then replace it with I'm fine.",
            "tension": "You call it keeping things easy. But they only meet the edited version. You keep measuring each sentence until nothing vulnerable remains visible.",
            "insight": "Sometimes the edit protects you from rejection while also hiding what connection needs.",
            "loopback": "The message was not too honest. It showed how visible you wanted to be.",
            "engagement_question": "Send this to someone who keeps hiding.",
            "like_cta": "Save this one.",
        }
        validated = validate_short_script(script, config)
        self.assertIn("generic_cta", validated["validation_failures"])
        self.assertEqual(validated["validation"], "forced")
        self.assertEqual(validated["hook_quality"], "strong")

    def test_concrete_contradiction_hook_passes_without_literal_signal(self):
        config = json.loads((ROOT / "config/pipeline_config.json").read_text())
        script = {
            "editorial_pov": "Shrinking can turn connection into a performance where honesty is always negotiated away.",
            "only_soft_reset_line": "Being easier to hold is not the same as being known.",
            "hook": "You shrink yourself down so other people feel big enough.",
            "tension": "You edit the honest need before anyone can reject it. Eventually they only know the smaller version you prepared.",
            "insight": "Sometimes this is incompatibility. Sometimes it is how the need was expressed. Neither answer requires disappearing.",
            "loopback": "The useful question is not who was too much. It is where honesty can remain visible.",
            "engagement_question": "When do you notice yourself editing what you need?",
            "like_cta": "Save this before you make your needs smaller again.",
        }
        validated = validate_short_script(script, config)
        self.assertEqual(validated["hook_quality"], "strong")

    def test_short_flags_viewer_superiority_framing(self):
        config = json.loads((ROOT / "config/pipeline_config.json").read_text())
        script = {
            "editorial_pov": "Protecting your needs should not require inventing a hierarchy between two people.",
            "only_soft_reset_line": "Compatibility is not proof that one person has a higher ceiling.",
            "hook": "You shrink yourself down so other people feel big enough.",
            "tension": "You keep editing every honest request before saying it.",
            "insight": "Some people can't hold depth. That is about their own capacity.",
            "loopback": "Someone else's low ceiling isn't your diagnosis.",
            "engagement_question": "When do you notice yourself becoming smaller?",
            "like_cta": "Save this before you edit the honest sentence.",
        }
        validated = validate_short_script(script, config)
        self.assertIn("superiority_framing", validated["validation_failures"])

    def test_judge_evidence_contains_real_ctas_and_longform_narration(self):
        short = _script_evidence({
            "hook": "Hook",
            "engagement_question": "Which moment felt familiar?",
            "like_cta": "Save this before the next conversation.",
        })
        self.assertEqual(short["like_cta"], "Save this before the next conversation.")
        longform = _script_evidence({
            "chapters": [{"id": 1, "label": "recognition", "voiceover": "Saturday night."}],
            "cta": "Subscribe for more.",
        })
        self.assertEqual(longform["chapters"][0]["voiceover"], "Saturday night.")
        self.assertEqual(longform["cta"], "Subscribe for more.")

    def test_judge_outage_preserves_existing_report(self):
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "10_judge_report.json"
            original = {"passed": True, "composite_score": 8.1}
            report_path.write_text(json.dumps(original))
            with patch("modules.creative_judge._call_judge", side_effect=OSError("offline")):
                with self.assertRaisesRegex(RuntimeError, "existing report preserved"):
                    run_creative_judge("test", temp, {})
            self.assertEqual(json.loads(report_path.read_text()), original)

    def test_longform_insufficient_capacity_is_a_hard_block(self):
        config = json.loads((ROOT / "config/longform_config.json").read_text())
        script = {
            "insufficient_story_capacity": True,
            "capacity_reason": "Only one observation is available.",
            "chapters": [
                {"voiceover": "word " * 140}
                for _ in range(5)
            ],
        }
        validated = validate_longform_script(script, config)
        self.assertIn("insufficient_story_capacity", validated["validation_failures"])
        self.assertEqual(validated["validation"], "needs_review")
        self.assertIn(
            "insufficient_story_capacity",
            _blocking_script_issues(validated, {"passes": True}),
        )

    def test_cached_blocked_longform_cannot_resume_into_media(self):
        with tempfile.TemporaryDirectory() as temp:
            script_path = Path(temp) / "02_longform_script.json"
            script_path.write_text(json.dumps({
                "validation": "needs_review",
                "human_review_required": True,
                "validation_failures": ["insufficient_story_capacity"],
                "argument_quality": "strong",
            }))
            with self.assertRaisesRegex(RuntimeError, "blocked before media generation"):
                _enforce_longform_script_gate(temp)

    def test_prompt_contract_contains_research_grounded_rules(self):
        short_prompt = (ROOT / "prompts/script_prompt.txt").read_text().lower()
        long_prompt = (ROOT / "prompts/longform_script_prompt.txt").read_text().lower()
        self.assertIn("observable moment", short_prompt)
        self.assertIn("silent quality check", short_prompt)
        self.assertIn("insufficient_story_capacity", long_prompt)
        self.assertIn("counterpoint and agency", long_prompt)
        self.assertIn("never announce that value is coming", long_prompt)


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

    def test_thumbnail_copy_is_fitted_not_truncated(self):
        line1, line2, combined = _variant_copy({
            "line1": "YOU'RE TOO COMFORTABLE",
            "line2": "and it's costing you more",
        })
        self.assertEqual(line1, "YOU'RE TOO COMFORTABLE")
        self.assertEqual(line2, "and it's costing you more")
        self.assertEqual(combined, "YOU'RE TOO COMFORTABLE / and it's costing you more")

    def test_post_render_thumbnail_selector_prefers_valid_b(self):
        selected, reason = _select_primary_variant([
            {"id": "A", "valid": True},
            {"id": "B", "valid": True},
            {"id": "C", "valid": True},
        ])
        self.assertEqual(selected["id"], "B")
        self.assertEqual(reason, "post_render_valid_b_preference")

    def test_longform_music_fade_finishes_on_final_frame(self):
        config = {"longform_end_hold_sec": 2.0, "longform_music_fade_out_sec": 1.5}
        voice_duration = 165.6
        final_duration = _planned_final_duration(voice_duration, config)
        fade_start = final_duration - config["longform_music_fade_out_sec"]
        self.assertEqual(final_duration, 167.6)
        self.assertGreater(fade_start, voice_duration)


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
