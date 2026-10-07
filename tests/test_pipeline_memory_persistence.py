import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import persist_pipeline_memory as memory


class PipelineMemoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / "remote.git"
        self.root = self.base / "runner"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", "-b", "main", str(self.root)], check=True, capture_output=True)
        memory.git(self.root, "config", "user.name", "Test")
        memory.git(self.root, "config", "user.email", "test@example.com")
        for names in memory.MEMORY_FILES.values():
            for name in names:
                (self.root / name).write_text("[]\n")
        (self.root / "unrelated.txt").write_text("original")
        memory.git(self.root, "add", ".")
        memory.git(self.root, "commit", "-m", "initial")
        memory.git(self.root, "remote", "add", "origin", str(self.remote))
        memory.git(self.root, "push", "origin", "main")

    def remote_file(self, name):
        return memory.git(self.remote, "show", f"main:{name}").stdout.decode()

    def update(self, name, value):
        (self.root / name).write_text(json.dumps(value))

    def test_only_changed_track_memory_is_saved(self):
        self.update(memory.MEMORY_FILES["short"][0], [{"video_id": "new"}])
        self.update(memory.MEMORY_FILES["long"][0], [{"video_id": "not-this-track"}])
        (self.root / "unrelated.txt").write_text("user change")
        (self.root / ".env").write_text("DO_NOT_SAVE=test")
        memory.git(self.root, "add", "unrelated.txt")
        before_index = memory.git(self.root, "diff", "--cached").stdout
        self.assertTrue(memory.persist(self.root, "short", "main"))
        self.assertEqual(json.loads(self.remote_file(memory.MEMORY_FILES["short"][0])), [{"video_id": "new"}])
        self.assertEqual(self.remote_file(memory.MEMORY_FILES["long"][0]), "[]\n")
        self.assertEqual(self.remote_file("unrelated.txt"), "original")
        self.assertEqual(memory.git(self.root, "diff", "--cached").stdout, before_index)
        self.assertNotIn(".env", memory.git(self.remote, "ls-tree", "--name-only", "main").stdout.decode())

    def test_no_changes_make_no_commit(self):
        before = memory.git(self.remote, "rev-parse", "main").stdout
        self.assertFalse(memory.persist(self.root, "short", "main"))
        self.assertEqual(memory.git(self.remote, "rev-parse", "main").stdout, before)

    def test_invalid_json_fails_before_push(self):
        (self.root / memory.MEMORY_FILES["short"][0]).write_text("broken {")
        before = memory.git(self.remote, "rev-parse", "main").stdout
        with self.assertRaises(json.JSONDecodeError):
            memory.persist(self.root, "short", "main")
        self.assertEqual(memory.git(self.remote, "rev-parse", "main").stdout, before)

    def test_concurrent_remote_commit_survives_retry(self):
        self.update(memory.MEMORY_FILES["short"][0], [{"video_id": "short"}])
        competitor = self.base / "other-runner"
        subprocess.run(["git", "clone", "-b", "main", str(self.remote), str(competitor)], check=True, capture_output=True)
        real_git = memory.git
        raced = False

        def git_with_race(root, *args, **kwargs):
            nonlocal raced
            if args[0] == "push" and not raced:
                raced = True
                name = memory.MEMORY_FILES["long"][0]
                (competitor / name).write_text('[{"video_id":"long"}]')
                real_git(competitor, "add", name)
                real_git(competitor, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "concurrent long")
                real_git(competitor, "push", "origin", "main")
            return real_git(root, *args, **kwargs)

        with patch.object(memory, "git", side_effect=git_with_race):
            self.assertTrue(memory.persist(self.root, "short", "main"))
        self.assertTrue(raced)
        self.assertEqual(json.loads(self.remote_file(memory.MEMORY_FILES["long"][0])), [{"video_id": "long"}])
        self.assertEqual(json.loads(self.remote_file(memory.MEMORY_FILES["short"][0])), [{"video_id": "short"}])

    def test_workflows_guard_mock_and_nonproduction_runs(self):
        root = Path(__file__).resolve().parents[1]
        for filename, track in (("run_pipeline.yml", "short"), ("run_longform.yml", "long")):
            source = (root / ".github/workflows" / filename).read_text()
            save = source.split("      - name: Save production memory for the next run", 1)[1]
            self.assertIn("always()", save)
            self.assertIn("inputs.mock == false", save)
            self.assertIn("github.ref_name == github.event.repository.default_branch", save)
            self.assertIn(f"--track {track}", save)
            self.assertIn("contents: write", source)


if __name__ == "__main__":
    unittest.main()
