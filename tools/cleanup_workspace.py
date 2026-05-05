"""
Workspace Cleanup Tool
=======================
Removes old run directories from workspace/ to prevent disk exhaustion.
Keeps the N most recent complete runs per track (Shorts / Longform).
Incomplete runs (no final video) are kept unless --all is passed.

Usage:
    python tools/cleanup_workspace.py             # dry-run preview
    python tools/cleanup_workspace.py --delete     # actually delete
    python tools/cleanup_workspace.py --keep 5     # keep 5 most recent complete runs
    python tools/cleanup_workspace.py --delete --all  # delete incomplete runs too
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WORKSPACE = "workspace"
DEFAULT_KEEP = 3

SHORTS_TERMINAL = "06_final_video.mp4"
LONGFORM_TERMINAL = "06_longform_video.mp4"


def _run_size_mb(run_dir: str) -> float:
    total = 0
    for dirpath, _, filenames in os.walk(run_dir):
        for f in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def _is_complete(run_dir: str) -> bool:
    return (
        os.path.exists(os.path.join(run_dir, SHORTS_TERMINAL))
        or os.path.exists(os.path.join(run_dir, LONGFORM_TERMINAL))
    )


def main():
    parser = argparse.ArgumentParser(description="Workspace Cleanup Tool")
    parser.add_argument("--delete", action="store_true", help="Actually delete (default is dry-run)")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help=f"Keep N most recent complete runs per track (default {DEFAULT_KEEP})")
    parser.add_argument("--all", dest="delete_all", action="store_true", help="Also delete incomplete runs")
    args = parser.parse_args()

    if not os.path.isdir(WORKSPACE):
        print(f"[cleanup] No workspace/ directory found.")
        return

    all_dirs = sorted(
        [os.path.join(WORKSPACE, d) for d in os.listdir(WORKSPACE) if os.path.isdir(os.path.join(WORKSPACE, d))]
    )

    shorts_complete = [d for d in all_dirs if os.path.basename(d).startswith("run_2") and _is_complete(d)]
    longform_complete = [d for d in all_dirs if os.path.basename(d).startswith("run_long_") and _is_complete(d)]
    incomplete = [d for d in all_dirs if not _is_complete(d)]

    to_delete: list[str] = []
    if len(shorts_complete) > args.keep:
        to_delete.extend(shorts_complete[: len(shorts_complete) - args.keep])
    if len(longform_complete) > args.keep:
        to_delete.extend(longform_complete[: len(longform_complete) - args.keep])
    if args.delete_all:
        to_delete.extend(incomplete)

    if not to_delete:
        print(f"[cleanup] Nothing to delete. (shorts: {len(shorts_complete)}, longform: {len(longform_complete)}, incomplete: {len(incomplete)})")
        return

    total_mb = sum(_run_size_mb(d) for d in to_delete)
    mode = "DELETE" if args.delete else "DRY RUN"

    print(f"\n{'='*54}")
    print(f" Workspace Cleanup [{mode}]")
    print(f"{'='*54}")
    print(f"  Complete Shorts:   {len(shorts_complete)} dirs  (keeping {args.keep})")
    print(f"  Complete Longform: {len(longform_complete)} dirs  (keeping {args.keep})")
    print(f"  Incomplete:        {len(incomplete)} dirs  {'(will delete)' if args.delete_all else '(keeping)'}")
    print(f"\n  To remove: {len(to_delete)} dirs, ~{total_mb:.0f} MB")
    for d in to_delete:
        mb = _run_size_mb(d)
        tag = "complete" if _is_complete(d) else "incomplete"
        print(f"    {os.path.basename(d):<42} {mb:>6.0f} MB  [{tag}]")

    if not args.delete:
        print(f"\n  Run with --delete to remove these.\n")
        return

    deleted, freed_mb = 0, 0.0
    for d in to_delete:
        mb = _run_size_mb(d)
        try:
            shutil.rmtree(d)
            print(f"  Deleted: {os.path.basename(d)} ({mb:.0f} MB)")
            deleted += 1
            freed_mb += mb
        except Exception as exc:
            print(f"  ERROR deleting {d}: {exc}")

    print(f"\n  Done. Removed {deleted} dirs, freed ~{freed_mb:.0f} MB.\n")


if __name__ == "__main__":
    main()
