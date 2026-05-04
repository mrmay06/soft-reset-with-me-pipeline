from __future__ import annotations

import json
import re
from pathlib import Path


CONFIG_PATH = Path("config/pipeline_config.json")
WORKFLOW_PATH = Path(".github/workflows/run_pipeline.yml")


def main() -> int:
    config = json.loads(CONFIG_PATH.read_text())
    weekly_slots = config.get("weekly_slots_et")
    if isinstance(weekly_slots, dict):
        expected = sum(len(v) for v in weekly_slots.values() if isinstance(v, list))
        label = "weekly_slots_et"
    else:
        expected = int(config.get("output_frequency_per_day", 0))
        label = "output_frequency_per_day"

    workflow = WORKFLOW_PATH.read_text()
    actual = len(re.findall(r"^\s*-\s*cron:\s*['\"]", workflow, flags=re.MULTILINE))

    if expected != actual:
        print(
            f"[schedule] Mismatch: {label}={expected}, "
            f"workflow cron entries={actual}"
        )
        return 1

    print(f"[schedule] OK: {actual} scheduled runs/week")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
