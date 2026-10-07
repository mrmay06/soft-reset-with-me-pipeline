from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules.longform_video_assembler import (
    _fetch_pexels_clip, _longform_clip_history, _remember_longform_clip,
    run_longform_video,
)
from tools.persist_pipeline_memory import MEMORY_FILES


class LongformClipMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "memory.json"
        self.config = {"longform_clip_memory_file": str(self.path)}

    def write(self, value):
        self.path.write_text(json.dumps(value))

    def test_missing_history_starts_empty(self):
        self.assertEqual(_longform_clip_history(self.config), (str(self.path), [], set(), set()))

    def test_recent_ids_are_namespaced_and_old_records_expire(self):
        now = datetime.now(timezone.utc)
        records = [
            {"provider": "pexels", "provider_id": "7", "file_hash": "a", "used_at": now.isoformat()},
            {"provider": "coverr", "provider_id": "7", "file_hash": "b", "used_at": now.isoformat()},
            {"provider": "pexels", "provider_id": "8", "file_hash": "c", "used_at": (now - timedelta(days=31)).isoformat()},
        ]
        self.write(records)
        _, memory, hashes, ids = _longform_clip_history(self.config)
        self.assertEqual(memory, records)
        self.assertEqual(hashes, {"a", "b"})
        self.assertEqual(ids, {"pexels:7", "coverr:7"})

    def test_invalid_dates_remain_blocked(self):
        self.write([{"provider": "pexels", "provider_id": "7", "file_hash": "a", "used_at": "unknown"}])
        self.assertEqual(_longform_clip_history(self.config)[2:], ({"a"}, {"pexels:7"}))

    def test_invalid_history_fails_safely(self):
        for value in ({}, [None], ["clip"]):
            with self.subTest(value=value):
                self.write(value)
                with self.assertRaises(RuntimeError):
                    _longform_clip_history(self.config)

    def test_remember_saves_bounded_history(self):
        memory = [{"old": index} for index in range(1000)]
        asset = {"provider": "coverr", "coverr_id": "fresh", "hash": "new", "query": "window"}
        saved = _remember_longform_clip(str(self.path), memory, asset, "video", 2)
        self.assertEqual(len(saved), 1000)
        self.assertEqual(saved[0], {"old": 1})
        self.assertEqual(json.loads(self.path.read_text()), saved)
        self.assertEqual(_longform_clip_history(self.config)[2:], ({"new"}, {"coverr:fresh"}))

    def test_provider_skips_remembered_id_and_duplicate_bytes(self):
        duplicate_hash = hashlib.sha256(b"duplicate").hexdigest()
        videos = [{"id": index, "video_files": [{"width": 1920, "link": f"clip-{index}"}]} for index in (1, 2, 3)]
        search = Mock()
        search.json.return_value = {"videos": videos}
        with patch.dict(os.environ, {"PEXELS_API_KEY": "test"}), patch(
            "modules.longform_video_assembler._top_result_order", side_effect=lambda items, config: items
        ), patch("modules.longform_video_assembler.requests.get", side_effect=[search, Mock(content=b"duplicate"), Mock(content=b"fresh")]) as get:
            asset = _fetch_pexels_clip(["window"], 0, str(self.root / "clip.mp4"), {}, {duplicate_hash}, {"pexels:1"})
        self.assertEqual(asset["pexels_id"], "3")
        self.assertEqual([call.args[0] for call in get.call_args_list][1:], ["clip-2", "clip-3"])

    def test_partial_render_failure_keeps_selected_clip_history(self):
        for name, value in (
            ("01_longform_research.json", {}), ("02_longform_script.json", {}),
            ("03_longform_metadata.json", {}), ("04_longform_voice_meta.json", {"duration_sec": 2}),
        ):
            (self.root / name).write_text(json.dumps(value))
        beats = [{"id": 1, "voiceover": "First."}, {"id": 2, "voiceover": "Second."}]
        asset = {"provider": "pexels", "pexels_id": "fresh", "hash": "bytes"}
        with patch("modules.longform_video_assembler._build_visual_beats", return_value=beats), patch(
            "modules.longform_video_assembler._fetch_stock_clip", side_effect=[asset, None]
        ), patch("modules.longform_video_assembler._clip_segment"):
            with self.assertRaisesRegex(RuntimeError, "beat 2"):
                run_longform_video("video", str(self.root), self.config)
        self.assertEqual(_longform_clip_history(self.config)[3], {"pexels:fresh"})
        self.assertFalse((self.root / "longform_render" / "cards").exists())

    def test_history_is_in_production_save_and_artifact_paths(self):
        name = "clip_memory_soft_reset_long.json"
        self.assertIn(name, MEMORY_FILES["long"])
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/run_longform.yml"
        self.assertIn(name, workflow.read_text())


if __name__ == "__main__":
    unittest.main()
