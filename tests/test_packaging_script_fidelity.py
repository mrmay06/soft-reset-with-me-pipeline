import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.metadata_agent import run_metadata
from modules.longform_metadata_agent import run_longform_metadata


class PackagingScriptFidelityTests(unittest.TestCase):
    def test_both_formats_receive_the_approved_ending(self):
        for longform in (False, True):
            with self.subTest(longform=longform), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                suffix = "_longform" if longform else ""
                research = {"topic": "Sharing a photo", "category": "Conversation Truths",
                            "source_fact": "Sometimes we anticipate rejection."}
                script = {"hook": "You nearly delete the photo.",
                          "chapters": [{"voiceover": "Send the photo; don't answer for them."}],
                          "ending": "Send the photo; don't answer for them."}
                (root / f"01{suffix}_research.json").write_text(json.dumps(research))
                (root / f"02{suffix}_script.json").write_text(json.dumps(script))
                config = {"metadata_model": "test", "youtube_category_id": "27",
                          "privacy_status": "private", "max_title_chars": 60}
                target = ("modules.longform_metadata_agent._generate_packaging" if longform
                          else "modules.metadata_agent._call_gemini_metadata")
                with patch(target, return_value={}) as generate:
                    if longform:
                        run_longform_metadata("test", directory, config)
                    else:
                        generate.return_value = {"title": "Before You Delete That Photo",
                                                 "description": "Try sharing one small thing.",
                                                 "tags": ["photo", "sharing", "communication"]}
                        run_metadata("test", directory, config)
                prompt = generate.call_args.args[0]
                self.assertIn("APPROVED FULL SCRIPT", prompt)
                self.assertIn(script["ending"], prompt)
                self.assertIn("overrides", prompt)


if __name__ == "__main__":
    unittest.main()
