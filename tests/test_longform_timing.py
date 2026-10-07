import math
from array import array
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from modules.longform_video_assembler import (
    _plan_beat_durations, _clip_segment, _concat,
    _finalize_longform, _validate_video,
)
from modules.video_assembler import _mix_audio


class LongformTimingTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
    def test_moving_tail_fades_without_freezing(self):
        config = {"longform_width": 160, "longform_height": 90, "longform_fps": 30,
                  "longform_end_hold_sec": 3.5, "longform_moving_tail": True,
                  "longform_end_fade_sec": 3.5, "longform_crf": 0}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, voice, output = (str(root / name) for name in ("source.mp4", "voice.wav", "output.mp4"))
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "testsrc2=s=160x90:r=30:d=4.5", "-c:v", "libx264", source],
                           check=True, capture_output=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=1", voice], check=True, capture_output=True)
            features = _finalize_longform(source, voice, None, output, config, 1)
            self.assertTrue(features["moving_tail"])
            self.assertEqual(features["ending_fade_sec"], 3.5)
            raw = subprocess.run(["ffmpeg", "-v", "error", "-i", output, "-an",
                                  "-vf", "format=gray", "-f", "rawvideo", "-"],
                                 check=True, capture_output=True).stdout
            size = 160 * 90
            frames = [raw[i:i + size] for i in range(0, len(raw), size)]
            self.assertAlmostEqual(len(frames) / 30, 4.5, delta=.05)
            self.assertGreater(len(set(frames[35:100])), 50)
            self.assertGreater(sum(frames[35]) / size, 50)
            self.assertLess(sum(frames[-1]) / size, 3)

    def test_short_beats_no_longer_inflate_timeline(self):
        beats = [{"voiceover": "word " * words} for words in [1, 2, 4, 10, 30, 60]]
        voice_duration = 165.6
        durations = _plan_beat_durations(beats, voice_duration, 30)
        self.assertAlmostEqual(sum(durations), voice_duration)
        self.assertLess(durations[0], 3.2)
        old_total = sum(max(3.2, voice_duration * words / 107) for words in [1, 2, 4, 10, 30, 60])
        self.assertGreater(old_total, voice_duration)

    def test_frame_rounding_does_not_accumulate(self):
        for seconds in (2.171, 120.015, 165.6, 302.123):
            for fps in (24, 30, 60):
                beats = [{"voiceover": "word " * (index + 1)} for index in range(30)]
                durations = _plan_beat_durations(beats, seconds, fps)
                self.assertEqual(round(sum(durations) * fps), math.ceil(seconds * fps))
                self.assertGreaterEqual(sum(durations) + 1e-9, seconds)
                self.assertLess(sum(durations) - seconds, 1 / fps + 1e-9)
                self.assertTrue(all(duration >= 1 / fps for duration in durations))

    def test_invalid_or_impossible_timeline_blocks_render(self):
        for beats, seconds, fps in (([], 10, 30), ([{}], 0, 30),
                                    ([{}], float("nan"), 30), ([{}], 10, 0),
                                    ([{}, {}], .01, 30)):
            with self.assertRaises(ValueError):
                _plan_beat_durations(beats, seconds, fps)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
    def test_actual_clip_concat_and_final_silent_hold(self):
        # Tiny generated fixtures exercise real encoding without APIs or stock downloads.
        config = {"longform_width": 160, "longform_height": 90, "longform_fps": 30,
                  "longform_crf": 0, "longform_validation_min_sec": 0,
                  "longform_end_hold_sec": 2, "film_overlay_enabled": False}
        voice_duration = 1.171
        beats = [{"voiceover": "one"}, {"voiceover": "two words"}, {"voiceover": "three more words"}]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            segments = []
            for index, (color, duration) in enumerate(zip(("red", "green", "blue"), _plan_beat_durations(beats, voice_duration, 30))):
                source = root / f"source{index}.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                                f"color=c={color}:s=160x90:r=30:d=0.2", "-c:v", "libx264", str(source)],
                               check=True, capture_output=True)
                segment = str(root / f"segment{index}.mp4")
                _clip_segment(str(source), duration, segment, config)
                segments.append(segment)
            voice = str(root / "voice.wav")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                            f"sine=frequency=440:duration={voice_duration}", voice], check=True, capture_output=True)
            concat = str(root / "concat.mp4")
            _concat(segments, concat)
            output = str(root / "final.mp4")
            features = _finalize_longform(concat, voice, None, output, config, voice_duration)
            result = _validate_video(output, config, voice_duration + 2)
            self.assertAlmostEqual(result["duration_sec"], voice_duration + 2, delta=.05)
            self.assertEqual(features["end_hold_sec"], 2)
            hashes = subprocess.run(["ffmpeg", "-v", "error", "-i", output, "-an", "-f", "framemd5", "-"],
                                    check=True, capture_output=True, text=True).stdout
            frames = [line.split(",")[-1].strip() for line in hashes.splitlines() if not line.startswith("#")]
            self.assertGreater(len(set(frames[:30])), 1)  # clips actually change
            self.assertEqual(len(set(frames[-50:])), 1)  # last frame held ~2 seconds
            tail = subprocess.run(["ffmpeg", "-v", "error", "-i", output, "-ss", "2.0", "-vn",
                                   "-f", "s16le", "-acodec", "pcm_s16le", "-"], check=True, capture_output=True).stdout
            self.assertTrue(tail)
            self.assertFalse(any(tail))  # narration is silent during the hold
            with self.assertRaisesRegex(RuntimeError, "timing mismatch"):
                _validate_video(output, config, voice_duration + 5)

            mixed = str(root / "mixed.aac")
            _mix_audio(voice, voice, voice_duration + 2, mixed, fade_out_sec=1.5)
            music_output = str(root / "with_music.mp4")
            _finalize_longform(concat, mixed, None, music_output, config, voice_duration)
            _validate_video(music_output, config, voice_duration + 2)

            def audio_level(start):
                data = subprocess.run(["ffmpeg", "-v", "error", "-i", music_output,
                                       "-ss", str(start), "-t", "0.1", "-vn", "-f", "s16le",
                                       "-acodec", "pcm_s16le", "-"], check=True, capture_output=True).stdout
                samples = array("h")
                samples.frombytes(data)
                return sum(abs(sample) for sample in samples) / max(1, len(samples))

            # Music remains after narration and fades toward the actual ending.
            self.assertGreater(audio_level(2.0), 10)
            self.assertLess(audio_level(3.0), audio_level(2.0) / 2)


if __name__ == "__main__":
    unittest.main()
