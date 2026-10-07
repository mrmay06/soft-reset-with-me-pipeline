import tempfile
import unittest
from unittest.mock import patch
from modules import longform_video_assembler as video


class LongformFilterContinuityTests(unittest.TestCase):
    def test_finalizer_prevents_metadata_reinitialization(self):
        config = {"film_overlay_enabled": False, "longform_end_hold_sec": 3.5,
                  "longform_moving_tail": True}
        with tempfile.TemporaryDirectory() as directory, patch.object(video, "_run_ffmpeg") as render:
            video._finalize_longform("joined.mp4", "audio.aac", None,
                                    directory + "/video.mp4", config, 10)
        command = render.call_args.args[0]
        self.assertEqual(command[command.index("-reinit_filter") + 1], "0")
        self.assertIn("[0:v]setsar=1", command[command.index("-filter_complex") + 1])

    def test_new_segments_have_consistent_square_pixel_metadata(self):
        with patch.object(video, "_run_ffmpeg") as render:
            video._clip_segment("clip.mp4", 2, "segment.mp4", {})
        command = render.call_args.args[0]
        self.assertIn("setsar=1", command[command.index("-vf") + 1])
