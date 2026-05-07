"""
Weekly Strategy — Orchestrator
================================
Runs the full weekly strategy cycle in order:
  1. Fetch analytics from YouTube API
  2. Pre-process into grouped comparisons
  3. AI analysis → proposed verdict

After this completes, strategy/strategy_memory_proposed.json is automatically
promoted to strategy/strategy_memory.json. Archived history remains available
for rollback.

Usage:
    python tools/weekly_strategy.py
    python tools/weekly_strategy.py --week 2026-W20
    python tools/weekly_strategy.py --dry-run            # analytics fetch only, no AI
    python tools/weekly_strategy.py --skip-fetch         # use existing cache
    python tools/weekly_strategy.py --skip-video-watch   # skip Gemini video upload
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from tools.weekly_analytics_fetch import run_fetch
from tools.weekly_preprocess import run_preprocess
from tools.weekly_analysis import run_analysis

STRATEGY_FILE = "strategy/strategy_memory.json"
PROPOSED_FILE = "strategy/strategy_memory_proposed.json"


def _current_week() -> str:
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc)
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main():
    parser = argparse.ArgumentParser(description="Weekly Strategy Cycle")
    parser.add_argument("--week", default=None, help="ISO week label e.g. 2026-W20")
    parser.add_argument("--dry-run", action="store_true", help="Run analytics fetch only (no AI analysis)")
    parser.add_argument("--skip-fetch", action="store_true", help="Skip analytics fetch, use existing cache")
    parser.add_argument("--skip-video-watch", action="store_true", help="Skip Gemini video watching in analysis")
    args = parser.parse_args()

    week = args.week or _current_week()
    start = time.time()

    print(f"\n{'='*60}")
    print(f" Soft Reset With Me — Weekly Strategy Cycle")
    print(f" Week: {week}")
    print(f"{'='*60}\n")

    # Step 1: Fetch
    if not args.skip_fetch:
        print("Step 1/3 — Fetching YouTube Analytics\n")
        t0 = time.time()
        cache_path = run_fetch(week_label=week, dry_run=args.dry_run)
        print(f"\nFetch done in {round(time.time()-t0, 1)}s → {cache_path}\n")
    else:
        print("Step 1/3 — Analytics fetch SKIPPED (--skip-fetch)\n")

    if args.dry_run:
        print("Dry-run mode: stopping after analytics fetch.")
        return

    # Step 2: Preprocess
    print("Step 2/3 — Pre-processing comparisons\n")
    t0 = time.time()
    comparison_path = run_preprocess(week_label=week)
    print(f"\nPreprocess done in {round(time.time()-t0, 1)}s → {comparison_path}\n")

    # Step 3: Analysis
    print("Step 3/3 — AI Strategy Analysis\n")
    t0 = time.time()
    proposed_path = run_analysis(week_label=week, skip_video_watch=args.skip_video_watch)
    print(f"\nAnalysis done in {round(time.time()-t0, 1)}s → {proposed_path}\n")

    total = round(time.time() - start, 1)

    print(f"{'='*60}")
    print(f" Weekly cycle complete in {total}s")
    print(f"{'='*60}")
    shutil.copy(PROPOSED_FILE, STRATEGY_FILE)
    print(f"\n Auto-promoted weekly strategy: {PROPOSED_FILE} → {STRATEGY_FILE}")
    print(f"""
 ROLLBACK:
    cp strategy/analysis_history/<previous-week>_verdict.json {STRATEGY_FILE}
""")


if __name__ == "__main__":
    main()
