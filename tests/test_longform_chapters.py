import json
from pathlib import Path
import tempfile
import unittest

from modules.longform_caption_agent import _write_ass, _caption_events, _title_case_caption_text
from modules.longform_metadata_agent import (
    _validate_chapter_titles, fallback_chapter_titles, run_longform_metadata_mock,
)
from modules.longform_research_agent import run_longform_research_mock
from modules.longform_script_agent import run_longform_script_mock
from utils.longform_chapters import (
    apply_longform_chapters, caption_word_timings, chapter_start_times, format_timestamp,
    insert_chapter_block, strip_chapter_block, validate_chapters,
)
from utils.longform_packaging import require_synchronized_packaging

SCRIPT = {"chapters": [
    {"id": 1, "label": "hook", "voiceover": "You're on the tram home and you almost send it. " * 3},
    {"id": 2, "label": "name the pain", "voiceover": "If someone asked, you'd say you didn't want to bother them. " * 3},
    {"id": 3, "label": "hidden pattern", "voiceover": "Nobody decides this in one night. It's taught in 3 small lessons. " * 3},
    {"id": 4, "label": "closing note", "voiceover": "So here's the question. Did they miss it, or did they never see it? " * 3},
]}
DESCRIPTION = ("The line that stops you.\n\nA softer second paragraph.\n\nWhat would you say? Drop it below.\n\n"
               "Subscribe for softer resets — @SoftResetWithMe\n\n#SoftResetWithMe #SelfWorth")


def whisper_events(script: dict, seconds_per_word: float = 0.5) -> list[tuple[float, float, str]]:
    """Caption events shaped like real whisper output: title case, contractions split, numbers spelled."""
    events, cursor = [], 0.0
    for chapter in script["chapters"]:
        for word in chapter["voiceover"].replace("You're", "You Are").replace("3", "three").split():
            events.append((cursor, cursor + seconds_per_word - 0.05, _title_case_caption_text(word)))
            cursor += seconds_per_word
    return events


class ChapterTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def words(self, events):
        path = self.root / "captions.ass"
        _write_ass(events, str(path))
        return caption_word_timings(str(path))

    def test_aligns_chapter_openings_despite_tokenization_differences(self):
        events = whisper_events(SCRIPT)
        # Whisper sometimes collapses two words into one caption event at a shared onset.
        start, end, text = events[40]
        events[40:42] = [(start, events[41][1], text + " " + events[41][2])]
        starts = chapter_start_times(SCRIPT, self.words(events))
        self.assertEqual([item["method"] for item in starts],
                         ["first_chapter"] + ["caption_alignment"] * 3)
        expected = [0.0]
        for chapter in SCRIPT["chapters"][:-1]:
            expected.append(expected[-1] + 0.5 * len(chapter["voiceover"].replace("You're", "You Are").split()))
        for item, seconds in zip(starts, expected):
            self.assertAlmostEqual(item["start_sec"], seconds, delta=0.02)

    def test_unalignable_chapter_falls_back_to_word_count_estimate(self):
        events = whisper_events(SCRIPT)
        boundary = sum(len(ch["voiceover"].replace("You're", "You Are").split()) for ch in SCRIPT["chapters"][:2])
        for index in range(boundary - 2, boundary + 10):
            start, end, _ = events[index]
            events[index] = (start, end, "Mumble")
        starts = chapter_start_times(SCRIPT, self.words(events))
        self.assertEqual(starts[1]["method"], "caption_alignment")
        self.assertEqual(starts[2]["method"], "word_count_estimate")
        self.assertEqual(starts[3]["method"], "caption_alignment")
        self.assertTrue(starts[1]["start_sec"] < starts[2]["start_sec"] < starts[3]["start_sec"])
        self.assertAlmostEqual(starts[2]["start_sec"], boundary * 0.5, delta=3)


class ChapterRulesTests(unittest.TestCase):
    def chapters(self, *starts):
        return [{"ids": [str(i + 1)], "title": f"Part {i + 1}", "start_sec": start, "method": "caption_alignment"}
                for i, start in enumerate(starts)]

    def test_formats_and_keeps_valid_chapters(self):
        items, reason = validate_chapters(self.chapters(0.0, 40.74, 94.56, 145.8), 320.7)
        self.assertIsNone(reason)
        self.assertEqual([item["timestamp"] for item in items], ["0:00", "0:40", "1:34", "2:25"])
        self.assertEqual(format_timestamp(3725), "1:02:05")

    def test_short_chapters_merge_into_neighbours(self):
        items, reason = validate_chapters(self.chapters(0.0, 5.0, 40.0, 46.0, 90.0, 140.0), 200.0)
        self.assertIsNone(reason)
        self.assertEqual([item["ids"] for item in items], [["1", "2", "3"], ["4"], ["5"], ["6"]])
        self.assertEqual(items[0]["start_sec"], 0)
        # A short final chapter folds into the previous one.
        items, _ = validate_chapters(self.chapters(0.0, 30.0, 60.0, 95.0), 100.0)
        self.assertEqual(items[-1]["ids"], ["3", "4"])

    def test_too_few_chapters_are_omitted(self):
        items, reason = validate_chapters(self.chapters(0.0, 30.0, 35.0), 60.0)
        self.assertEqual(items, [])
        self.assertIn("only 2", reason)

    def test_block_sits_before_subscribe_line_and_is_replaced_not_duplicated(self):
        first = insert_chapter_block(DESCRIPTION, "Chapters\n0:00 One\n0:40 Two\n1:30 Three")
        second = insert_chapter_block(first, "Chapters\n0:00 One\n0:41 Two\n1:30 Three")
        self.assertEqual(second.count("Chapters"), 1)
        self.assertIn("0:41 Two", second)
        self.assertLess(second.index("Drop it below"), second.index("Chapters"))
        self.assertLess(second.index("1:30 Three"), second.index("Subscribe"))
        self.assertEqual(strip_chapter_block(second), DESCRIPTION)

    def test_strip_keeps_prose_that_starts_with_a_time(self):
        text = "2:00 am and you are still awake.\n\nSubscribe for softer resets — @SoftResetWithMe"
        self.assertEqual(strip_chapter_block(text), text)


class ChapterTitleTests(unittest.TestCase):
    def test_model_titles_are_kept_unless_clinical_or_malformed(self):
        titles = _validate_chapter_titles([
            {"id": 1, "title": "Why it still replays."},
            {"id": "2", "title": "Your attachment pattern explained"},
            {"id": 3, "title": "Hook"},
        ], SCRIPT)
        self.assertEqual(titles[0], {"id": "1", "title": "Why it still replays", "source": "model"})
        self.assertEqual(titles[1], {"id": "2", "title": "The part that hurts", "source": "fallback"})
        self.assertEqual(titles[2]["title"], "What keeps pulling you back")
        self.assertEqual(titles[3]["title"], "Before you go")

    def test_unknown_labels_fall_back_deterministically(self):
        script = {"chapters": [{"id": 1, "label": "the price of safe silence", "voiceover": "x"},
                               {"id": 2, "label": "pattern", "voiceover": "Nobody decides this in one night."}]}
        titles = fallback_chapter_titles(script)
        self.assertEqual([item["title"] for item in titles], ["The price of safe silence", "Nobody decides this in one"])
        self.assertEqual(titles, fallback_chapter_titles(script))


class ApplyChaptersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.metadata = {
            "title": "Title B", "primary_variant_id": "B", "thumbnail_text": "COPY B / text",
            "primary_thumbnail_output_file": "thumb_B.png", "primary_thumbnail_prompt_file": "prompt_B.txt",
            "description": DESCRIPTION,
            "title_variants": [{"id": key, "title": f"Title {key}"} for key in "ABC"],
            "chapter_titles": [{"id": str(i), "title": f"Title {i}"} for i in range(1, 5)],
        }
        thumbnail = {"primary_variant_id": "B", "variants": [
            {"id": "B", "valid": True, "output_file": "thumb_B.png", "prompt_file": "prompt_B.txt",
             "thumbnail_text": "COPY B / text"}]}
        (self.root / "thumb_B.png").write_bytes(b"B")
        (self.root / "07_longform_thumbnail.png").write_bytes(b"B")
        (self.root / "prompt_B.txt").write_text("brief")
        (self.root / "07_longform_thumbnail_meta.json").write_text(json.dumps(thumbnail))
        (self.root / "02_longform_script.json").write_text(json.dumps(SCRIPT))
        (self.root / "03_longform_metadata.json").write_text(json.dumps(self.metadata))
        (self.root / "04_longform_voice_meta.json").write_text(json.dumps({"duration_sec": 100.0}))
        _write_ass(whisper_events(SCRIPT), str(self.root / "04_longform_captions.ass"))

    def metadata_now(self):
        return json.loads((self.root / "03_longform_metadata.json").read_text())

    def test_resume_is_idempotent_and_recaptioning_updates_the_block(self):
        self.assertTrue(apply_longform_chapters(str(self.root), {}))
        result = self.metadata_now()
        self.assertIn("Chapters\n0:00 Title 1\n0:16 Title 2\n0:33 Title 3\n0:51 Title 4", result["description"])
        self.assertEqual(result["youtube_chapters"]["method"], "caption_alignment")
        require_synchronized_packaging(str(self.root), result)

        self.assertFalse(apply_longform_chapters(str(self.root), {}))
        self.assertEqual(self.metadata_now()["description"].count("Chapters"), 1)

        judge = self.root / "10_judge_report.json"
        judge.write_text('{"passed":true,"gate":"passed"}')
        _write_ass(whisper_events(SCRIPT, 0.55), str(self.root / "04_longform_captions.ass"))
        (self.root / "04_longform_voice_meta.json").write_text(json.dumps({"duration_sec": 110.0}))
        self.assertTrue(apply_longform_chapters(str(self.root), {}))
        description = self.metadata_now()["description"]
        self.assertEqual(description.count("Chapters"), 1)
        self.assertIn("0:18 Title 2", description)
        self.assertFalse(judge.exists())
        self.assertEqual(len(list(self.root.glob("10_judge_report_before_chapter_sync_*.json"))), 1)

    def test_disabled_flag_removes_block(self):
        apply_longform_chapters(str(self.root), {})
        self.assertTrue(apply_longform_chapters(str(self.root), {"longform_chapters_enabled": False}))
        result = self.metadata_now()
        self.assertEqual(result["description"], DESCRIPTION)
        self.assertEqual(result["youtube_chapters"]["status"], "disabled")

    def test_invalid_chapters_leave_description_untouched(self):
        (self.root / "04_longform_voice_meta.json").write_text(json.dumps({"duration_sec": 100.0}))
        _write_ass(whisper_events(SCRIPT, 0.1), str(self.root / "04_longform_captions.ass"))
        self.assertFalse(apply_longform_chapters(str(self.root), {}))
        result = self.metadata_now()
        self.assertEqual(result["description"], DESCRIPTION)
        self.assertEqual(result["youtube_chapters"]["status"], "omitted")

    def test_mock_pipeline_produces_chapters(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "config/longform_config.json").read_text())
        directory = str(self.root / "mock")
        Path(directory).mkdir()
        run_longform_research_mock("test", directory, config)
        script = run_longform_script_mock("test", directory, config)
        run_longform_metadata_mock("test", directory, config)
        duration = round(script["word_count"] / 155 * 60, 1)
        (Path(directory) / "04_longform_voice_meta.json").write_text(json.dumps({"duration_sec": duration}))
        _write_ass(_caption_events(script, duration), str(Path(directory) / "04_longform_captions.ass"))
        self.assertTrue(apply_longform_chapters(directory, config))
        chapters = json.loads((Path(directory) / "03_longform_metadata.json").read_text())["youtube_chapters"]
        self.assertEqual(chapters["status"], "published")
        self.assertEqual(chapters["chapters"][0]["timestamp"], "0:00")
        self.assertGreaterEqual(len(chapters["chapters"]), 3)


if __name__ == "__main__":
    unittest.main()
