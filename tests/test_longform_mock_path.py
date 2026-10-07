import json
from pathlib import Path
import tempfile
import unittest

from main_long import _apply_test_2min_overrides, _enforce_longform_script_gate
from modules.longform_research_agent import run_longform_research_mock
from modules.longform_script_agent import run_longform_script_mock


class LongformMockPathTests(unittest.TestCase):
    def test_mock_script_fits_production_and_two_minute_ranges(self):
        base = json.loads((Path(__file__).resolve().parents[1] / "config/longform_config.json").read_text())
        for config in (base, _apply_test_2min_overrides(dict(base))):
            with self.subTest(minimum=config["longform_target_words_min"]), tempfile.TemporaryDirectory() as directory:
                run_longform_research_mock("test", directory, config)
                script = run_longform_script_mock("test", directory, config)
                self.assertGreaterEqual(script["word_count"], config["longform_target_words_min"])
                self.assertLessEqual(script["word_count"], config["longform_target_words_max"])
                self.assertEqual(script["validation"], "passed")
                self.assertEqual(script["chapters"][0]["label"], "hook")
                self.assertEqual(script["chapters"][-1]["label"], "closing note")
                self.assertEqual(script["argument_review"]["status"], "mock")
                with self.assertRaisesRegex(RuntimeError, "argument review"):
                    _enforce_longform_script_gate(directory)


if __name__ == "__main__":
    unittest.main()
