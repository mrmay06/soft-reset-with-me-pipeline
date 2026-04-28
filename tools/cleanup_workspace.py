"""
Workspace cleanup — deletes run directories older than KEEP_DAYS.
Run daily via cron. Keeps the last N days of runs, deletes everything else.
"""

import os
import shutil
from datetime import datetime, timedelta

WORKSPACE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "workspace")
KEEP_DAYS = 3


def run_cleanup(keep_days: int = KEEP_DAYS):
    if not os.path.exists(WORKSPACE_DIR):
        print("[cleanup] No workspace directory found — nothing to do.")
        return

    cutoff = datetime.utcnow() - timedelta(days=keep_days)
    all_runs = sorted([
        d for d in os.listdir(WORKSPACE_DIR)
        if d.startswith("run_") and os.path.isdir(os.path.join(WORKSPACE_DIR, d))
    ])

    deleted = 0
    kept = 0
    freed_mb = 0.0

    for run_name in all_runs:
        # Parse date from run_YYYYMMDD_HHMMSS
        try:
            date_str = run_name.replace("run_", "").split("_")[0]
            run_date = datetime.strptime(date_str, "%Y%m%d")
        except ValueError:
            continue

        run_path = os.path.join(WORKSPACE_DIR, run_name)

        if run_date < cutoff:
            size_mb = sum(
                os.path.getsize(os.path.join(dp, f))
                for dp, _, files in os.walk(run_path)
                for f in files
            ) / (1024 * 1024)
            shutil.rmtree(run_path)
            freed_mb += size_mb
            deleted += 1
            print(f"[cleanup] Deleted {run_name} ({size_mb:.1f} MB)")
        else:
            kept += 1

    print(f"[cleanup] Done. Deleted {deleted} runs, kept {kept}. Freed {freed_mb:.1f} MB.")


if __name__ == "__main__":
    run_cleanup()
