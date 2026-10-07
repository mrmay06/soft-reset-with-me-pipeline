import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from modules.tts import _call_gemini_tts
from modules.longform_audio_agent import run_longform_audio, STABILIZATION_FILTER


class AudioProvenanceTests(unittest.TestCase):
    def test_raw_pcm_is_preserved_and_processing_is_recorded(self):
        pcm = b"\x01\x00" * 100
        response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(inline_data=SimpleNamespace(data=pcm, mime_type="audio/L16;rate=24000"))
        ]))])
        client = Mock()
        client.models.generate_content.return_value = response
        def encode(command, **kwargs):
            Path(command[-1]).write_bytes(b"encoded")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), patch(
            "modules.tts._genai", Mock(Client=Mock(return_value=client))
        ), patch("modules.tts._genai_types", Mock()), patch("subprocess.run", side_effect=encode):
            output = Path(tmp) / "voice.mp3"
            info = _call_gemini_tts("Narration", {"tts_model": "test", "tts_voice": "Puck", "tts_speed": 1.1}, str(output))
            with wave.open(str(Path(tmp) / info["raw_audio"]), "rb") as raw:
                self.assertEqual(raw.readframes(100), pcm)
                self.assertEqual(raw.getframerate(), 24000)
            self.assertEqual([stage["stage"] for stage in info["processing"]], ["mp3_encoding", "leading_silence_trim", "tempo"])
            self.assertEqual(output.read_bytes(), b"encoded")
            client.models.generate_content.assert_called_once()

    def test_longform_keeps_pre_stabilization_and_does_not_claim_verified_continuity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "02_longform_script.json").write_text(json.dumps({"chapters": [{"voiceover": "You wait."}]}))
            def generate(text, config, path):
                Path(path).write_bytes(b"original")
                return {"raw_audio": "raw.wav", "processing": [{"stage": "mp3_encoding"}]}
            def stabilize(path):
                Path(path).write_bytes(b"processed")
            with patch("modules.longform_audio_agent._call_gemini_tts", side_effect=generate) as tts, patch(
                "modules.longform_audio_agent._stabilize_longform_voice", side_effect=stabilize
            ), patch("modules.longform_audio_agent._validate_audio", return_value={"duration_sec": 2, "validation": "passed"}):
                meta = run_longform_audio("video", tmp, {"tts_voice": "Puck", "tts_model": "test"})
            self.assertEqual((root / meta["pre_stabilization_audio"]).read_bytes(), b"original")
            self.assertEqual((root / "04_longform_voice.mp3").read_bytes(), b"processed")
            self.assertFalse(meta["continuity_verified"])
            self.assertNotIn("continuity_lock", meta)
            self.assertEqual(meta["processing"][-1]["filter"], STABILIZATION_FILTER)
            tts.assert_called_once()

    def test_comparison_survives_stabilization_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "02_longform_script.json").write_text(json.dumps({"chapters": []}))
            def generate(text, config, path):
                Path(path).write_bytes(b"original")
            with patch("modules.longform_audio_agent._call_gemini_tts", side_effect=generate), patch(
                "modules.longform_audio_agent._stabilize_longform_voice", side_effect=RuntimeError("failed")
            ):
                with self.assertRaises(RuntimeError):
                    run_longform_audio("video", tmp, {})
            self.assertEqual((root / "04_longform_voice_pre_stabilization.mp3").read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
