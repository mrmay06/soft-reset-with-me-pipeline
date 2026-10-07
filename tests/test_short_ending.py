import unittest
import json
from pathlib import Path
from unittest.mock import patch

from modules.video_assembler import (
    _assemble_final, _assemble_without_captions,
    _compensate_scene_durations_for_xfade, _ending_fade_filter,
    _xfaded_duration,
)


class ShortEndingTests(unittest.TestCase):
    def test_production_configs_use_matching_tails_and_fades(self):
        root = Path(__file__).resolve().parents[1]
        short = json.loads((root / "config/pipeline_config.json").read_text())
        long = json.loads((root / "config/longform_config.json").read_text())
        self.assertEqual(short["end_hold_sec"], 3.5)
        self.assertEqual(short["end_fade_sec"], 3.5)
        self.assertEqual(long["longform_end_hold_sec"], 3.5)
        self.assertEqual(long["longform_end_fade_sec"], 3.5)
        self.assertEqual(long["longform_music_fade_out_sec"], 3.5)
        self.assertTrue(long["longform_moving_tail"])
    def test_tail_extends_last_moving_scene_without_extra_transition(self):
        scenes = [{"duration_sec": 10}, {"duration_sec": 10}]
        original = _compensate_scene_durations_for_xfade(scenes, 0, .4)
        extended = _compensate_scene_durations_for_xfade(scenes, 0, .4, 3.5)
        self.assertEqual(extended[0], original[0])
        self.assertAlmostEqual(extended[-1] - original[-1], 3.5)
        self.assertAlmostEqual(_xfaded_duration(list(zip(["a", "b"], extended)), .4), 23.5)

    def test_fade_starts_at_narration_end(self):
        self.assertEqual(_ending_fade_filter({"end_fade_sec": 3.5}, 42.47),
                         "fade=t=out:st=38.970:d=3.5")
        self.assertEqual(_ending_fade_filter({}, 42.47), "null")

    def test_both_caption_and_fallback_renders_fade(self):
        config = {"end_fade_sec": 3.5}
        with patch("modules.video_assembler._run_ffmpeg") as run, \
             patch("modules.video_assembler._build_caption_filter", return_value=("null", "test")):
            _assemble_final("video", "audio", "captions", "output", config, 42.47)
            command = run.call_args.args[0]
            self.assertIn("fade=t=out:st=38.970:d=3.5", command[command.index("-filter_complex") + 1])
            self.assertEqual(command[command.index("-map") + 1], "[vfinal]")
            _assemble_without_captions("video", "audio", "output", config, 42.47)
            command = run.call_args.args[0]
            self.assertIn("fade=t=out:st=38.970:d=3.5", command[command.index("-filter_complex") + 1])


if __name__ == "__main__":
    unittest.main()
