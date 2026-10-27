import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from modules import image_gen
from modules.tts import _LEADING_SILENCE_TRIM, _silence_filter


def _duration(path: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


class PauseCompressionTests(unittest.TestCase):
    def test_longform_and_unconfigured_runs_only_trim_leading_silence(self):
        self.assertEqual(_silence_filter({}), _LEADING_SILENCE_TRIM)

    def test_shorts_config_enables_pause_compression(self):
        with open("config/pipeline_config.json") as handle:
            config = json.load(handle)
        flt = _silence_filter(config)
        self.assertIn("stop_periods=-1", flt)
        self.assertIn("stop_duration=0.2", flt)
        self.assertIn("stop_silence=0.2", flt)

    def test_filter_shortens_a_long_gap_but_keeps_both_tones(self):
        config = {"tts_pause_trim_after_sec": 0.2, "tts_pause_keep_sec": 0.2}
        with tempfile.TemporaryDirectory() as directory:
            source = os.path.join(directory, "in.wav")
            out = os.path.join(directory, "out.wav")
            # 1s tone, 1.2s silence, 1s tone
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=1.2",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                            "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", source], check=True)
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", source,
                            "-af", _silence_filter(config), out], check=True)
            self.assertAlmostEqual(_duration(source), 3.2, delta=0.05)
            self.assertLess(_duration(out), 2.6)
            self.assertGreater(_duration(out), 2.2)


class SensitiveDescriptionTests(unittest.TestCase):
    def test_slug_terms_match_whole_words_only(self):
        hit = {"page_url": "https://www.pexels.com/video/a-shirtless-man-on-a-bed-123/"}
        self.assertEqual(image_gen._sensitive_description(hit), "shirtless")
        for slug in ("scarf-on-a-chair-1", "a-person-wearing-leather-jacket-6808549", "bracelet-on-a-wrist-9"):
            self.assertEqual(image_gen._sensitive_description({"page_url": f"https://www.pexels.com/video/{slug}/"}), "")

    def test_pools_drop_described_sensitive_clips(self):
        clean = {"provider_id": "1", "page_url": "https://www.pexels.com/video/hands-texting-1/"}
        flagged = {"provider_id": "2", "page_url": "https://www.pexels.com/video/woman-in-hospital-bed-2/"}
        with patch.object(image_gen, "_query_alternates", return_value=["q"]), \
             patch.object(image_gen, "_pexels_candidates", return_value=[clean, flagged]):
            pools = image_gen._build_pools([{"id": 1, "pexels_query": "q"}], [], {})
        self.assertEqual([c["provider_id"] for c in pools[1]], ["1"])


class ReviewedSelectionTests(unittest.TestCase):
    scene = {"id": 3, "covers_dialogue": "You said definitely.", "duration_sec": 3.0}

    def candidates(self):
        return [{"provider_id": str(i), "query": "q", "duration": 6.0} for i in range(1, 5)]

    def select(self, verdicts, rejected=None, config=None):
        statuses = iter(verdicts)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(image_gen, "_download", side_effect=lambda candidate, path: f"hash{candidate['provider_id']}") as download, \
             patch.object(image_gen, "_frame_hash", side_effect=lambda path, frame: "0"), \
             patch.object(image_gen, "_review_clip", side_effect=lambda *args: {"status": next(statuses), "reason": "r"}):
            picked = image_gen._select_reviewed_clip(self.scene, self.candidates(), os.path.join(directory, "c.mp4"),
                                                     directory, config or {}, lambda h, p: False, set(), rejected)
        return picked, download

    def test_unsafe_clip_is_skipped_for_the_next_one(self):
        picked, _ = self.select(["unsafe", "pass"])
        self.assertEqual(picked[0]["provider_id"], "2")
        self.assertEqual(picked[3]["status"], "pass")

    def test_off_topic_is_only_a_backup_when_the_budget_runs_out(self):
        rejected = set()
        picked, download = self.select(["off_topic", "unsafe"], rejected, {"clip_review_max_checks_per_scene": 2})
        self.assertEqual(picked[0]["provider_id"], "1")
        self.assertEqual(download.call_args.args[0]["provider_id"], "1")  # re-downloaded to the output path
        self.assertNotIn("1", rejected)
        self.assertIn("2", rejected)

    def test_no_safe_candidate_returns_none(self):
        picked, _ = self.select(["unsafe"] * 4)
        self.assertIsNone(picked)

    def test_review_outage_does_not_stop_production(self):
        picked, _ = self.select(["unavailable"])
        self.assertEqual(picked[0]["provider_id"], "1")

    def test_review_answers_are_parsed_strictly(self):
        scene, candidate = dict(self.scene), {"provider_id": "1", "query": "q", "duration": 6.0}
        cases = [({"safe": True, "fits": True}, "pass"), ({"safe": True, "fits": False}, "off_topic"),
                 ({"safe": False, "fits": True}, "unsafe"), ({"fits": True}, "unsafe"), ([], "unsafe")]
        for verdict, expected in cases:
            with self.subTest(verdict=verdict), \
                 patch.object(image_gen, "_clip_frames", return_value=[b"jpg"]), \
                 patch("utils.gemini_client.generate_json_with_images", return_value=verdict):
                self.assertEqual(image_gen._review_clip("v.mp4", candidate, scene, {}, ".")["status"], expected)
        with patch.object(image_gen, "_clip_frames", side_effect=RuntimeError("ffmpeg")):
            self.assertEqual(image_gen._review_clip("v.mp4", candidate, scene, {}, ".")["status"], "unavailable")
        self.assertEqual(image_gen._review_clip("v.mp4", candidate, scene, {"clip_review_enabled": False}, ".")["status"],
                         "disabled")


if __name__ == "__main__":
    unittest.main()
