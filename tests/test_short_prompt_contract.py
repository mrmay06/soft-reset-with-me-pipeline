import json
from pathlib import Path
from string import Formatter
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ShortPromptContractTests(unittest.TestCase):
    def test_template_uses_only_existing_runtime_inputs(self):
        template = (ROOT / "prompts/script_prompt.txt").read_text()
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        expected = {
            "topic", "category", "angle_type", "hook_seed", "content_basis",
            "content_format", "emotional_trigger", "psych_concept", "core_claim",
            "editorial_seed", "performance_insights", "video_id", "generated_at",
            "target_words_min", "target_words_max", "hard_words_min", "hard_words_max",
        }
        self.assertEqual(fields, expected)
        for content_format in ("scenario", "truth_drop", "reframe", "hot_take", "list"):
            values = {name: "test input" for name in expected}
            values.update(content_format=content_format, target_words_min=60,
                          target_words_max=90, hard_words_min=45, hard_words_max=110)
            rendered = template.format(**values)
            contract = json.loads(rendered[rendered.index("{\n"):])
            self.assertEqual(contract["content_format"], content_format)
            self.assertEqual(contract["prompt_version"], "soft-reset-script-v2.7")

    def test_output_fields_preserve_pipeline_contract(self):
        template = (ROOT / "prompts/script_prompt.txt").read_text()
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        rendered = template.format(**{name: "test" for name in fields})
        contract = json.loads(rendered[rendered.index("{\n"):])
        self.assertEqual(set(contract), {
            "script_version", "prompt_version", "video_id", "topic", "category",
            "content_format", "emotional_trigger", "psych_concept", "core_claim",
            "editorial_pov", "standout_line", "only_soft_reset_line", "hook",
            "tension", "insight", "loopback", "cta", "engagement_question",
            "like_cta", "thumbnail_text", "word_count", "estimated_duration_sec",
            "validation", "validation_notes", "generated_at",
        })


if __name__ == "__main__":
    unittest.main()
