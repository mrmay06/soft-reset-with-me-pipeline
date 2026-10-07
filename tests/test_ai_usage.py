from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from utils.ai_usage import configure_usage, measured_call, usage_stage


class AIUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ai_usage.jsonl"
        configure_usage(self.temp.name)
        self.addCleanup(patch.stopall)
        self.addCleanup(self.clear_context)

    def clear_context(self):
        import utils.ai_usage as usage
        usage._path = None

    def records(self):
        return [json.loads(line) for line in self.path.read_text().splitlines()]

    def test_google_usage_and_stage_without_request_or_response_text(self):
        response = SimpleNamespace(text="SECRET RESPONSE", usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=3, thoughts_token_count=2))
        with usage_stage("Research"):
            returned = measured_call("google", "test", "json", lambda **kwargs: response, model="test", contents="SECRET PROMPT")
        self.assertIs(returned, response)
        record = self.records()[0]
        self.assertEqual(record["stage"], "Research")
        self.assertEqual(record["usage"]["prompt_token_count"], 10)
        self.assertNotIn("SECRET", self.path.read_text())

    def test_anthropic_cache_tokens_are_preserved(self):
        measured_call("anthropic", "test", "review", lambda: {"usage": {"input_tokens": 4, "output_tokens": 2, "cache_read_input_tokens": 10}})
        self.assertEqual(self.records()[0]["usage"]["cache_read_input_tokens"], 10)

    def test_missing_usage_is_unavailable_not_zero(self):
        measured_call("google", "test", "tts", lambda: object())
        self.assertEqual(self.records()[0]["usage_status"], "unavailable")
        self.assertEqual(self.records()[0]["usage"], {})

    def test_each_attempt_records_failure_without_error_message(self):
        def fail():
            raise ValueError("SECRET CREDENTIAL")
        with self.assertRaises(ValueError):
            measured_call("google", "test", "json", fail)
        measured_call("google", "test", "json", lambda: {})
        records = self.records()
        self.assertEqual([record["status"] for record in records], ["api_failed", "response_received"])
        self.assertEqual(records[0]["error_type"], "ValueError")
        self.assertNotIn("SECRET", self.path.read_text())

    def test_parallel_calls_share_stage_and_write_valid_separate_rows(self):
        with usage_stage("candidate_scoring"), ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: measured_call("google", "test", "json", lambda: {}), range(20)))
        self.assertEqual(len(self.records()), 20)
        self.assertTrue(all(record["stage"] == "candidate_scoring" for record in self.records()))

    def test_logging_failure_does_not_repeat_paid_work(self):
        with patch("pathlib.Path.open", side_effect=OSError("blocked")):
            self.assertEqual(measured_call("google", "test", "json", lambda: "result"), "result")


if __name__ == "__main__":
    unittest.main()
