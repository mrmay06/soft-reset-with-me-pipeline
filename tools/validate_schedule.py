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
        short_slots = sum(len(v) for v in weekly_slots.values() if isinstance(v, list))
        longform_slots = sum(
            len(v) for v in config.get("longform_weekly_slots_et", {}).values()
            if isinstance(v, list)
        )
        expected = short_slots + longform_slots
        label = "weekly_slots_et + longform_weekly_slots_et"
    else:
        expected = int(config.get("output_frequency_per_day", 0))
        label = "output_frequency_per_day"

    workflow = WORKFLOW_PATH.read_text()
    expected_crons = expected * 2 if config.get("dst_safe_dual_cron", False) else expected
    actual = len(re.findall(r"^\s*-\s*cron:\s*['\"]", workflow, flags=re.MULTILINE))

    if expected_crons != actual:
        print(
            f"[schedule] Mismatch: {label}={expected}, "
            f"expected cron entries={expected_crons}, workflow cron entries={actual}"
        )
        return 1

    suffix = " (DST-safe dual UTC crons)" if config.get("dst_safe_dual_cron", False) else ""
    print(f"[schedule] OK: {expected} local scheduled runs/week, {actual} cron entries{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
