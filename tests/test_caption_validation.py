import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.caption_validation import validate_words, captions_are_current, save_caption_report
from modules.longform_caption_agent import run_longform_captions
from modules.caption_agent import run_captions


class CaptionValidationTests(unittest.TestCase):
    def words(self):
        return [{"word": "You", "start": 0.1, "end": 0.3},
                {"word": "wait.", "start": 1.5, "end": 1.9}]

    def test_actual_pauses_remain_valid(self):
        evidence = validate_words(self.words(), "You wait.", 2)
        self.assertEqual(evidence["script_coverage"], 1)
        self.assertEqual(evidence["timing_source"], "audio_transcription")

    def test_empty_or_invalid_timestamps_block(self):
        for words in ([], [{"word": "You", "start": -1, "end": 1}],
                      [{"word": "You", "start": 0, "end": float("nan")}],
                      [{"word": "You", "start": 1, "end": 0}],
                      [{"word": "You", "start": 0, "end": 3}],
                      [{"word": "You", "start": 0, "end": 1}, {"word": "wait", "start": 0.5, "end": 1.5}]):
            with self.subTest(words=words), self.assertRaises(RuntimeError):
                validate_words(words, "You wait", 2)

    def test_missing_and_hallucinated_speech_block(self):
        for transcript in ("You wait for their reply every single night", "A different statement entirely"):
            with self.assertRaises(RuntimeError):
                validate_words(self.words(), transcript, 2)
        with self.assertRaises(RuntimeError):
            validate_words(self.words(), "You", 2)

    def test_punctuation_case_and_apostrophe_variations_are_tolerated(self):
        words = [{"word": "DON’T!", "start": 0, "end": 1}]
        self.assertEqual(validate_words(words, "Don't.", 1)["script_coverage"], 1)

    def test_report_binds_voice_captions_and_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            audio, caption = Path(tmp) / "voice.mp3", Path(tmp) / "captions.ass"
            audio.write_bytes(b"voice")
            caption.write_text("captions")
            save_caption_report(str(caption), str(audio), "You wait.", validate_words(self.words(), "You wait.", 2))
            self.assertTrue(captions_are_current(str(caption), str(audio), "You wait."))
            self.assertFalse(captions_are_current(str(caption), str(audio), "New speech"))
            audio.write_bytes(b"changed")
            self.assertFalse(captions_are_current(str(caption), str(audio), "You wait."))
            audio.write_bytes(b"voice")
            caption.write_text("edited")
            self.assertFalse(captions_are_current(str(caption), str(audio), "You wait."))

    def test_production_tracks_reject_empty_alignment_and_save_no_approval(self):
        for longform in (False, True):
            with self.subTest(longform=longform), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                if longform:
                    (root / "02_longform_script.json").write_text(json.dumps({"chapters": [{"voiceover": "You wait."}]}))
                    (root / "04_longform_voice_meta.json").write_text(json.dumps({"duration_sec": 2}))
                    function, target = run_longform_captions, "modules.longform_caption_agent._words_from_audio"
                    report = root / "04_longform_captions.validation.json"
                else:
                    (root / "02_script.json").write_text(json.dumps({"hook": "You wait."}))
                    function, target = run_captions, "modules.caption_agent._get_word_timestamps"
                    report = root / "04_captions.validation.json"
                with patch(target, return_value=[]), patch("modules.caption_agent._audio_duration", return_value=2):
                    with self.assertRaises(RuntimeError):
                        function("video", tmp, {})
                self.assertNotEqual(json.loads(report.read_text())["status"], "passed")

    def test_longform_saves_real_alignment_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "02_longform_script.json").write_text(json.dumps({"chapters": [{"voiceover": "You wait."}]}))
            (root / "04_longform_voice_meta.json").write_text(json.dumps({"duration_sec": 2}))
            (root / "04_longform_voice.mp3").write_bytes(b"voice")
            with patch("modules.longform_caption_agent._words_from_audio", return_value=self.words()):
                run_longform_captions("video", tmp, {})
            self.assertTrue(captions_are_current(str(root / "04_longform_captions.ass"), str(root / "04_longform_voice.mp3"), "You wait."))


if __name__ == "__main__":
    unittest.main()
