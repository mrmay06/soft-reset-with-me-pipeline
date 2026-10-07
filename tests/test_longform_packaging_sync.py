import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from utils.longform_packaging import synchronize_longform_packaging, require_synchronized_packaging
from utils.notify import send_longform_upload_confirmation
from modules.longform_uploader import run_longform_upload


class LongformPackagingSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.metadata = {
            "title": "Title C", "primary_variant_id": "C", "thumbnail_text": "Copy C",
            "description": "Preserve this", "tags": ["original"],
            "title_variants": [{"id": key, "title": f"Title {key}"} for key in "ABC"],
            "thumbnail_variants": [{"id": key, "line1": f"COPY {key}", "line2": "original text"} for key in "ABC"],
        }
        self.thumbnail = {"primary_variant_id": "B", "variants": [
            {"id": key, "valid": True, "output_file": f"thumb_{key}.png",
             "prompt_file": f"prompt_{key}.txt", "thumbnail_text": f"COPY {key} / rendered text",
             "line1": f"COPY {key}", "line2": "rendered text"} for key in "ABC"
        ]}
        for key in "ABC":
            (self.root / f"thumb_{key}.png").write_bytes(f"fixture {key}".encode())
            (self.root / f"prompt_{key}.txt").write_text(f"Actual edit brief {key}")
        (self.root / "07_longform_thumbnail.png").write_bytes(b"fixture B")
        self.save()

    def save(self):
        (self.root / "03_longform_metadata.json").write_text(json.dumps(self.metadata))
        (self.root / "07_longform_thumbnail_meta.json").write_text(json.dumps(self.thumbnail))

    def test_rendered_b_replaces_requested_c_consistently(self):
        judge = self.root / "10_judge_report.json"
        judge.write_text('{"passed":true,"gate":"passed"}')
        self.assertTrue(synchronize_longform_packaging(str(self.root)))
        self.assertFalse(judge.exists())
        archives = list(self.root.glob("10_judge_report_before_packaging_sync_*.json"))
        self.assertEqual(len(archives), 1)
        self.assertTrue(json.loads(archives[0].read_text())["passed"])
        result = json.loads((self.root / "03_longform_metadata.json").read_text())
        self.assertEqual(result["primary_variant_id"], "B")
        self.assertEqual(result["requested_primary_variant_id"], "C")
        self.assertEqual(result["title"], "Title B")
        self.assertEqual(result["thumbnail_text"], "COPY B / rendered text")
        self.assertEqual(result["primary_thumbnail_prompt_file"], "prompt_B.txt")
        self.assertEqual(result["description"], self.metadata["description"])
        self.assertEqual(result["title_variants"], self.metadata["title_variants"])
        require_synchronized_packaging(str(self.root), result)
        self.assertFalse(synchronize_longform_packaging(str(self.root)))

    def test_fallback_c_uses_matching_title(self):
        self.thumbnail["primary_variant_id"] = "C"
        (self.root / "07_longform_thumbnail.png").write_bytes(b"fixture C")
        self.save()
        self.assertTrue(synchronize_longform_packaging(str(self.root)))
        result = json.loads((self.root / "03_longform_metadata.json").read_text())
        self.assertEqual(result["title"], "Title C")
        self.assertEqual(result["primary_thumbnail_prompt_file"], "prompt_C.txt")

    def test_missing_title_or_invalid_render_blocks_sync(self):
        self.metadata["title_variants"] = [{"id": "C", "title": "Title C"}]
        self.save()
        with self.assertRaisesRegex(RuntimeError, "matching title"):
            synchronize_longform_packaging(str(self.root))
        self.thumbnail["variants"][1]["valid"] = False
        self.save()
        with self.assertRaisesRegex(RuntimeError, "valid rendered"):
            synchronize_longform_packaging(str(self.root))

    def test_missing_prompt_or_wrong_upload_image_blocks_sync(self):
        (self.root / "07_longform_thumbnail.png").write_bytes(b"fixture C")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            synchronize_longform_packaging(str(self.root))
        (self.root / "07_longform_thumbnail.png").write_bytes(b"fixture B")
        (self.root / "prompt_B.txt").unlink()
        with self.assertRaisesRegex(RuntimeError, "missing"):
            synchronize_longform_packaging(str(self.root))

    def test_upload_mismatch_blocks_before_youtube_connection(self):
        with patch("modules.longform_uploader._get_youtube_client") as youtube:
            with self.assertRaisesRegex(RuntimeError, "packaging mismatch"):
                run_longform_upload("test", str(self.root), {})
            youtube.assert_not_called()

    def test_email_uses_actual_rendered_selection_and_brief(self):
        with patch("utils.notify._send_email_with_attachments") as send:
            send_longform_upload_confirmation("test", "Title C", "Not uploaded", self.metadata, self.thumbnail, str(self.root))
        subject, body, attachments = send.call_args.args
        self.assertIn("Title B", subject)
        self.assertIn("Primary:     Variant B", body)
        self.assertIn("Variant B (PRIMARY)", body)
        self.assertIn("Variant C (ALT)", body)
        self.assertIn("COPY B / rendered text", body)
        self.assertIn("Actual edit brief B", body)
        self.assertIn(str(self.root / "prompt_B.txt"), attachments)
        self.assertIn(str(self.root / "thumb_B.png"), attachments)


if __name__ == "__main__":
    unittest.main()
