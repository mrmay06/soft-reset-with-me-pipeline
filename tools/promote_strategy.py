"""
promote_strategy.py — Human-gated strategy promotion for Soft Reset With Me.

The weekly analysis writes to strategy/strategy_memory_proposed.json.
This tool is the ONLY way to promote it to strategy/strategy_memory.json (active).
Running this without reading the proposed strategy first is the wrong workflow.

Usage:
    python tools/promote_strategy.py --review     # print proposed strategy for review
    python tools/promote_strategy.py --promote    # promote proposed → active (requires --confirm)
    python tools/promote_strategy.py --promote --confirm

Workflow:
    1. Run weekly analysis:    python tools/weekly_strategy.py
    2. Review proposed:        python tools/promote_strategy.py --review
    3. Promote if approved:    python tools/promote_strategy.py --promote --confirm
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STRATEGY_DIR           = "strategy"
ACTIVE_STRATEGY_PATH   = os.path.join(STRATEGY_DIR, "strategy_memory.json")
PROPOSED_STRATEGY_PATH = os.path.join(STRATEGY_DIR, "strategy_memory_proposed.json")


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _print_diff(proposed: dict, active: dict):
    print("\n=== PROPOSED STRATEGY (not yet active) ===")
    print(f"  Version:         {proposed.get('version', 'untracked')}")
    print(f"  Generated:       {proposed.get('generated_at', '?')}")
    print(f"  Videos analyzed: {proposed.get('videos_analyzed', '?')}")

    for section in ("research", "script", "visuals", "metadata", "voice", "thumbnail"):
        new_section = proposed.get(section, {})
        old_section = active.get(section, {})
        if new_section != old_section:
            print(f"\n  [{section.upper()}] CHANGED:")
            print(f"    {json.dumps(new_section, indent=4)}")
        else:
            print(f"\n  [{section.upper()}] unchanged")

    experiments = proposed.get("experiment_slots", {})
    this_week = experiments.get("this_week", [])
    if this_week:
        print(f"\n  [EXPERIMENTS] this week: {json.dumps(this_week, indent=4)}")

    health = proposed.get("channel_health_signal", "")
    if health:
        print(f"\n  Channel health signal: {health}")

    override_check = proposed.get("brand_bible_override_check", "")
    if "conflict" in str(override_check).lower():
        print(f"\n  ⚠ BRAND BIBLE CONFLICT DETECTED: {override_check}")
    else:
        print(f"\n  Brand bible check: {override_check}")


def main():
    parser = argparse.ArgumentParser(description="Review and promote weekly strategy proposals for Soft Reset With Me")
    parser.add_argument("--review", action="store_true", help="Print proposed strategy vs active")
    parser.add_argument("--promote", action="store_true", help="Promote proposed to active")
    parser.add_argument("--confirm", action="store_true", help="Required with --promote to actually write")
    args = parser.parse_args()

    if not args.review and not args.promote:
        parser.print_help()
        return

    proposed = _load_json(PROPOSED_STRATEGY_PATH)
    if not proposed:
        print(f"[promote_strategy] No proposed strategy found at {PROPOSED_STRATEGY_PATH}")
        print("  Run: python tools/weekly_strategy.py")
        return

    active = _load_json(ACTIVE_STRATEGY_PATH)

    if args.review:
        _print_diff(proposed, active)
        if not args.promote:
            print("\nTo promote: python tools/promote_strategy.py --promote --confirm")
        return

    if args.promote:
        if not args.confirm:
            print("[promote_strategy] --confirm required. Review first with --review.")
            print("  python tools/promote_strategy.py --review")
            print("  python tools/promote_strategy.py --promote --confirm")
            sys.exit(1)

        _print_diff(proposed, active)
        print(f"\nPromoting {PROPOSED_STRATEGY_PATH} → {ACTIVE_STRATEGY_PATH}")

        import shutil
        os.makedirs(STRATEGY_DIR, exist_ok=True)
        shutil.copy2(PROPOSED_STRATEGY_PATH, ACTIVE_STRATEGY_PATH)

        print(f"[promote_strategy] Done. Strategy v{proposed.get('version')} is now active.")
        print("  The next pipeline run will use the new strategy context.")


if __name__ == "__main__":
    main()
