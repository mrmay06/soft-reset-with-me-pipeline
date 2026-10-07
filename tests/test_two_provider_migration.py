import base64
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

from modules.tts import _call_current_tts, _call_gemini_tts, _build_tts_input
from modules.longform_audio_agent import _build_longform_tts_input
from utils.claude_response import request_options, response_text


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x01\x00" * 100)
    return stream.getvalue()


class TwoProviderMigrationTests(unittest.TestCase):
    def test_all_configured_models_are_two_provider_targets(self):
        for name in ["pipeline", "longform"]:
            config = json.loads(Path(f"config/{name}_config.json").read_text())
            self.assertEqual(config["script_model"], "claude-sonnet-5-5")
            self.assertEqual(config["tts_model"], "gemini-3.8-flash-tts")
            for key, value in config.items():
                if key.endswith("_model") and key not in {"script_model", "tts_model"}:
                    self.assertEqual(value, "gemini-3.8-flash", key)

    def test_claude_skips_thinking_and_combines_text_blocks(self):
        message = SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="thinking", thinking="hidden"),
            SimpleNamespace(type="text", text='{"passes":'),
            SimpleNamespace(type="text", text='true}')])
        self.assertEqual(json.loads(response_text(message)), {"passes": True})
        self.assertEqual(request_options("claude-sonnet-5-5")["extra_body"]["thinking"]["type"], "between_tools")
        self.assertEqual(request_options("claude-sonnet-4-6"), {})

    def test_claude_rejects_truncation_and_empty_text(self):
        for message in [SimpleNamespace(stop_reason="max_tokens", content=[]),
                        SimpleNamespace(stop_reason="end_turn", content=[])]:
            with self.assertRaises(ValueError):
                response_text(message)

    def test_delivery_is_metadata_for_both_formats_and_usage_is_preserved(self):
        data = wav_bytes()
        http = Mock(ok=True)
        http.json.return_value = {"candidates": [{"content": {"parts": [
            {"text": "not audio"}, {"inlineData": {"mimeType": "audio/wav",
                "data": base64.b64encode(data).decode()}}]}}],
            "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 150}}
        for tts_input in [_build_tts_input({"hook": "You wait.", "body": "", "cta": ""}),
                          _build_longform_tts_input({"chapters": [{"voiceover": "You wait."}]})]:
            with patch("requests.post", return_value=http) as post:
                result = _call_current_tts("secret", tts_input,
                    {"tts_model": "gemini-3.8-flash-tts", "tts_voice": "Puck"})
            part = post.call_args.kwargs["json"]["contents"][0]["parts"][0]
            self.assertIn("You wait.", part["text"])
            self.assertNotIn("Warm,", part["text"])
            self.assertIn("style", part["speech_metadata"])
            self.assertNotIn("secret", post.call_args.args[0])
            self.assertEqual(result.usage_metadata["prompt_token_count"], 12)
            self.assertEqual(result.candidates[0].content.parts[0].inline_data.data, data)

    def test_new_wav_output_is_not_double_wrapped(self):
        data = wav_bytes()
        response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
            SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type="audio/wav"))]))])
        def encode(command, **kwargs):
            Path(command[-1]).write_bytes(b"encoded")
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), patch(
            "modules.tts._call_current_tts", return_value=response
        ), patch("subprocess.run", side_effect=encode):
            info = _call_gemini_tts("Warm.\n\nYou wait.",
                {"tts_model": "gemini-3.8-flash-tts", "tts_voice": "Puck"}, str(Path(tmp) / "voice.mp3"))
            self.assertEqual((Path(tmp) / info["raw_audio"]).read_bytes(), data)
            self.assertTrue(info["delivery_metadata_separate"])

    def test_rest_failure_does_not_expose_secret_body(self):
        http = Mock(ok=False, status_code=403)
        with patch("requests.post", return_value=http):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                _call_current_tts("secret", "You wait.",
                    {"tts_model": "gemini-3.8-flash-tts", "tts_voice": "Puck"})
        http.json.assert_not_called()
