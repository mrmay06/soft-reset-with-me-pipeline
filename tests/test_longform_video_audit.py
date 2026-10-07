import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules.video_audit_agent import (
    AUDIT_VERSION, _longform_context, _prompt, _video_fingerprint,
    enforce_longform_visual_gate, longform_audit_is_current, run_video_audit,
)


class LongformVideoAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {"longform_target_words_min": 700, "public_release_enabled": True}
        self.video = self.root / "06_longform_video.mp4"
        self.video.write_bytes(b"render-one")
        self.write("02_longform_script.json", {"chapters": [{"id": 1, "voiceover": "You put the phone down."}]})
        self.write("03_longform_metadata.json", {"title": "A quiet reset"})
        self.write("06_longform_render_meta.json", {"visual_assets": [{"beat_id": 1, "duration_sec": 2, "provider": "pexels"}], "end_hold_sec": 2})

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def audit(self, **updates):
        report = {"status": "ok", "track": "longform", "audit_version": AUDIT_VERSION,
                  "render_sha256": _video_fingerprint(str(self.video)), "blocking_visual_mismatches": []}
        report.update(updates)
        self.write("09_video_audit.json", report)

    def test_context_maps_narration_to_rendered_beats(self):
        context = _longform_context("video", str(self.root), self.config)
        scene = context["scene_map"][0]
        self.assertEqual(scene["covers_dialogue"], "You put the phone down.")
        self.assertEqual((scene["start_sec"], scene["end_sec"]), (0, 2))
        prompt = _prompt(context)
        self.assertIn("finished long-form video", prompt)
        self.assertIn("Different people and locations", prompt)
        self.assertIn("Generic but emotionally compatible footage is not blocking", prompt)

    def test_current_report_passes_and_changed_render_invalidates_it(self):
        self.audit()
        enforce_longform_visual_gate(str(self.root), self.config)
        self.video.write_bytes(b"render-two")
        self.assertFalse(longform_audit_is_current(str(self.root)))
        with self.assertRaisesRegex(RuntimeError, "stale"):
            enforce_longform_visual_gate(str(self.root), self.config)

    def test_failed_mock_old_and_missing_reports_cannot_approve_public(self):
        for updates in ({"status": "soft_failed"}, {"status": "mock"}, {"audit_version": 1}, {"track": "short"}):
            with self.subTest(updates=updates):
                self.audit(**updates)
                with self.assertRaises(RuntimeError):
                    enforce_longform_visual_gate(str(self.root), self.config)
        (self.root / "09_video_audit.json").unlink()
        with self.assertRaises(RuntimeError):
            enforce_longform_visual_gate(str(self.root), self.config)

    def test_contradiction_blocks_and_invalid_beat_is_rejected(self):
        for scene_id in (1, 99):
            self.audit(blocking_visual_mismatches=[{"scene_id": scene_id, "severity": "high", "confidence": "high", "reason": "Contradiction"}])
            with self.assertRaises(RuntimeError):
                enforce_longform_visual_gate(str(self.root), self.config)

    def test_disabled_check_blocks_public_but_private_bypasses_gate(self):
        with self.assertRaisesRegex(RuntimeError, "requires"):
            enforce_longform_visual_gate(str(self.root), {**self.config, "video_audit_enabled": False})
        enforce_longform_visual_gate(str(self.root), {"public_release_enabled": False})

    def test_longform_checker_uploads_correct_render_and_saves_fingerprint(self):
        model = Mock()
        model.generate_content.return_value.text = json.dumps({"audit_version": AUDIT_VERSION, "blocking_visual_mismatches": []})
        client = Mock()
        client.GenerativeModel.return_value = model
        with patch("modules.video_audit_agent._get_gemini_client", return_value=client), patch(
            "modules.video_audit_agent._upload_video", return_value=Mock(uri="test-uri")
        ) as upload:
            report = run_video_audit("video", str(self.root), self.config)
        self.assertEqual(upload.call_args.args[1], str(self.video))
        self.assertEqual(report["track"], "longform")
        self.assertTrue(longform_audit_is_current(str(self.root)))
        enforce_longform_visual_gate(str(self.root), self.config)

    def test_api_failure_is_saved_and_blocks_public(self):
        with patch("modules.video_audit_agent._get_gemini_client", side_effect=RuntimeError("offline")):
            report = run_video_audit("video", str(self.root), self.config)
        self.assertEqual(report["status"], "soft_failed")
        with self.assertRaises(RuntimeError):
            enforce_longform_visual_gate(str(self.root), self.config)

    def test_uploader_checks_gate_before_connecting_to_youtube(self):
        from modules.longform_uploader import run_longform_upload
        with patch("modules.longform_uploader.require_synchronized_packaging"), patch(
            "modules.longform_uploader._get_youtube_client"
        ) as youtube:
            with self.assertRaises(RuntimeError):
                run_longform_upload("video", str(self.root), self.config)
        youtube.assert_not_called()


if __name__ == "__main__":
    unittest.main()
