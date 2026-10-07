from datetime import datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def run_workflow_gate(event, schedule, now, enabled=True):
    """Execute the actual inline workflow gate without calling any services."""
    source = (ROOT / '.github/workflows/weekly_strategy.yml').read_text()
    block = source.split('        run: |\n', 1)[1].split('\n      - name:', 1)[0]
    code = '\n'.join(line[10:] for line in block.splitlines())
    import datetime as datetime_module
    import io
    import json
    import os
    from unittest.mock import patch

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now

    output = io.StringIO()
    config = io.StringIO(json.dumps({'automation_enabled': enabled}))
    def fake_open(path, mode='r'):
        return output if path == 'gate-output' else config
    # StringIO would otherwise be closed by the workflow's context manager.
    class OpenFile:
        def __init__(self, stream): self.stream = stream
        def __getattr__(self, name): return getattr(self.stream, name)
        def __enter__(self): return self.stream
        def __exit__(self, *args): return False
    with patch.dict(os.environ, {'GITHUB_EVENT_NAME': event, 'GITHUB_EVENT_SCHEDULE': schedule, 'GITHUB_OUTPUT': 'gate-output'}), patch.object(datetime_module, 'datetime', FrozenDatetime), patch('builtins.open', side_effect=lambda *args: OpenFile(fake_open(*args))):
        exec(compile(code, 'weekly_strategy_gate', 'exec'), {})
    return output.getvalue().strip()


class WeeklyStrategyScheduleTests(unittest.TestCase):
    def test_delayed_october_run_executes_active_cron(self):
        now = datetime(2026, 10, 5, 12, 59, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(run_workflow_gate('schedule', '0 8 * * 1', now), 'should_run=true')

    def test_summer_duplicate_cron_is_skipped(self):
        now = datetime(2026, 10, 5, 12, 59, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(run_workflow_gate('schedule', '0 9 * * 1', now), 'should_run=false')

    def test_winter_active_cron_runs_even_when_delayed(self):
        now = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(run_workflow_gate('schedule', '0 9 * * 1', now), 'should_run=true')
        self.assertEqual(run_workflow_gate('schedule', '0 8 * * 1', now), 'should_run=false')

    def test_disabled_and_missing_schedule_fail_closed(self):
        now = datetime(2026, 10, 5, 12, 59, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(run_workflow_gate('schedule', '0 8 * * 1', now, False), 'should_run=false')
        self.assertEqual(run_workflow_gate('schedule', '', now), 'should_run=false')

    def test_manual_run_remains_available(self):
        now = datetime(2026, 10, 7, 12, 0, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(run_workflow_gate('workflow_dispatch', '', now, False), 'should_run=true')


if __name__ == '__main__':
    unittest.main()
