import json
from pathlib import Path
from string import Formatter
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LongformPromptContractTests(unittest.TestCase):
    def test_template_uses_existing_runtime_inputs(self):
        template = (ROOT / "prompts/longform_script_prompt.txt").read_text()
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        self.assertEqual(fields, {
            "duration_label", "topic", "working_title", "longform_format",
            "content_pillar", "core_claim", "editorial_seed", "only_soft_reset_line",
            "viewer_pain", "psych_concept", "content_basis", "retention_hook",
            "chapter_arc", "visual_mood", "performance_insights", "target_words_min",
            "target_words_max", "hard_words_min", "hard_words_max", "generated_at",
        })
        for content_format in ("emotional_deep_dive", "pattern_breakdown",
                               "one_truth_expanded", "soft_reset_letter", "conversation_you_needed"):
            values = {name: "test input" for name in fields}
            values.update(longform_format=content_format, duration_label="2-minute test",
                          target_words_min=200, target_words_max=300,
                          hard_words_min=180, hard_words_max=330, chapter_arc="[]")
            rendered = template.format(**values)
            contract = json.loads(rendered[rendered.index("{\n"):])
            self.assertEqual(contract["longform_format"], content_format)

    def test_output_schema_and_spoken_fields_unchanged(self):
        template = (ROOT / "prompts/longform_script_prompt.txt").read_text()
        fields = {name for _, name, _, _ in Formatter().parse(template) if name}
        rendered = template.format(**{name: "test" for name in fields})
        contract = json.loads(rendered[rendered.index("{\n"):])
        self.assertEqual(set(contract), {
            "insufficient_story_capacity", "capacity_reason", "topic", "working_title",
            "content_pillar", "longform_format", "core_claim", "editorial_pov",
            "narrative_spine", "psychology_engine", "counterpoint", "decision_tool",
            "mirror_moment", "only_soft_reset_line", "engagement_question",
            "estimated_duration_sec", "word_count", "chapters", "visual_brief", "cta", "generated_at",
        })
        self.assertEqual(set(contract["chapters"][0]), {"id", "label", "purpose", "voiceover"})
        self.assertEqual(set(contract["visual_brief"][0]), {"chapter_id", "scene_role", "stock_queries"})
        self.assertIn("Only chapter voiceover is spoken", template)


if __name__ == "__main__":
    unittest.main()
