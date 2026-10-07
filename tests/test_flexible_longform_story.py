import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import longform_script_agent as script
from modules import longform_research_agent as research


ROOT = Path(__file__).resolve().parents[1]


class FlexibleLongformStoryTests(unittest.TestCase):
    def config(self):
        return {"longform_target_words_min": 200, "longform_target_words_max": 300,
                "longform_hard_words_min": 180, "longform_hard_words_max": 330}

    def test_four_chapters_are_not_rewritten_for_count_alone(self):
        draft = {"insufficient_story_capacity": False, "chapters": [
            {"id": index, "voiceover": "word " * 60} for index in range(4)]}
        result = script._validate_script(draft, self.config())
        self.assertEqual(result["validation"], "passed")
        self.assertNotIn("too_few_chapters", result["validation_warnings"])
        self.assertEqual(result["validation_failures"], [])

    def test_empty_narration_and_hard_length_still_block(self):
        for chapters in ([], [{"voiceover": ""}], [{"voiceover": "too short"}]):
            result = script._validate_script({"insufficient_story_capacity": False, "chapters": chapters}, self.config())
            self.assertIn("word_count_hard", result["validation_failures"])
            self.assertEqual(result["validation"], "needs_review")

    def test_insufficient_story_capacity_still_blocks(self):
        result = script._validate_script({"insufficient_story_capacity": True,
                                         "chapters": [{"voiceover": "word " * 240}]}, self.config())
        self.assertIn("insufficient_story_capacity", result["validation_failures"])

    def test_fallback_outline_timings_are_removed(self):
        outline = {"topic": "An emotional observation", "chapter_arc": [
            {"chapter": "opening", "purpose": "recognition", "duration_sec": 25},
            {"chapter": "ending", "purpose": "resolution", "duration_sec": 130}]}
        with tempfile.TemporaryDirectory() as directory:
            config = {"research_model": "test", "longform_duration_label": "2-minute test",
                      "topic_memory_file": str(Path(directory) / "topics.json")}
            with patch.object(research, "_generate_longform_topic", side_effect=RuntimeError("offline")) as model, patch.object(research, "_fallback_longform_topic", return_value=outline):
                result = research.run_longform_research("test", directory, config)
            self.assertIn("2-minute test", model.call_args.args[0])
            self.assertTrue(all("duration_sec" not in chapter for chapter in result["chapter_arc"]))
            self.assertEqual(result["chapter_arc"][0]["purpose"], "recognition")

    def test_cached_outline_timings_do_not_reach_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "01_longform_research.json").write_text(json.dumps({
                "chapter_arc": [{"chapter": "opening", "purpose": "recognition", "duration_sec": 9876}]}))
            with patch.object(script, "_call_model", side_effect=RuntimeError("capture only")) as model:
                with self.assertRaisesRegex(RuntimeError, "capture only"):
                    script.run_longform_script("test", directory, {"script_model": "test"})
            prompt = model.call_args.args[0]
            self.assertNotIn("9876", prompt)
            self.assertIn("recognition", prompt)

    def test_prompt_keeps_quality_without_fixed_emotional_formula(self):
        prompt = (ROOT / "prompts/longform_script_prompt.txt").read_text()
        for phrase in ("at least 3 times", "exactly one direct", "must get heavier", "roughly every 35-60"):
            self.assertNotIn(phrase, prompt)
        for phrase in ("COUNTERPOINT AND AGENCY (mandatory)", "DECISION TOOL (mandatory)",
                       "Never announce that value is coming", "Do not pad it", "HUMAN PSYCHOLOGY LAYER (optional)"):
            self.assertIn(phrase, prompt)


if __name__ == "__main__":
    unittest.main()
