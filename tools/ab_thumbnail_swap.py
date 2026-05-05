"""
A/B Thumbnail Rotation Tool
============================
Scans workspace/ for longform runs that have been uploaded to YouTube.
After 48h on primary → swaps to next variant.
After 96h → swaps to final variant.
Logs each swap to 07_longform_thumbnail_swap_log.json inside the run dir.

Usage:
    python tools/ab_thumbnail_swap.py
    python tools/ab_thumbnail_swap.py --dry-run
    python tools/ab_thumbnail_swap.py --run-dir workspace/long_20260505_111757
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    print("[ab_swap] google-api-python-client not installed — pip install google-api-python-client")
    sys.exit(1)

WORKSPACE = "workspace"
SWAP_LOG = "07_longform_thumbnail_swap_log.json"
UPLOAD_META = "09_longform_upload_meta.json"
THUMB_META = "07_longform_thumbnail_meta.json"

ROTATION_HOURS = [48, 96]  # hours after upload_at to swap to variant index 1, 2


def _get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def _load(path: str) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(data, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 0.0


def _target_variant_index(hours_elapsed: float) -> int:
    """Returns 0, 1, or 2 based on how long since upload."""
    for i, threshold in enumerate(ROTATION_HOURS):
        if hours_elapsed < threshold:
            return i
    return len(ROTATION_HOURS)


def _find_eligible_runs(workspace: str) -> list[str]:
    if not os.path.isdir(workspace):
        return []
    runs = []
    for name in sorted(os.listdir(workspace)):
        run_dir = os.path.join(workspace, name)
        if not os.path.isdir(run_dir):
            continue
        if not name.startswith("long_"):
            continue
        if os.path.exists(os.path.join(run_dir, UPLOAD_META)) and os.path.exists(os.path.join(run_dir, THUMB_META)):
            runs.append(run_dir)
    return runs


def process_run(run_dir: str, dry_run: bool = False) -> None:
    upload_meta = _load(os.path.join(run_dir, UPLOAD_META))
    thumb_meta = _load(os.path.join(run_dir, THUMB_META))

    youtube_video_id = upload_meta.get("youtube_video_id", "")
    uploaded_at = upload_meta.get("uploaded_at", "")
    if not youtube_video_id or youtube_video_id == "MOCK_NOT_UPLOADED":
        return
    if not uploaded_at:
        return

    variants = thumb_meta.get("variants", [])
    if len(variants) < 2:
        return

    hours = _hours_since(uploaded_at)
    target_idx = _target_variant_index(hours)
    target_idx = min(target_idx, len(variants) - 1)

    # Load swap log to check what's already been applied
    swap_log_path = os.path.join(run_dir, SWAP_LOG)
    swap_log: list[dict] = []
    if os.path.exists(swap_log_path):
        swap_log = _load(swap_log_path)  # type: ignore[assignment]

    last_applied_idx = -1
    if swap_log:
        last_applied_idx = swap_log[-1].get("variant_index", -1)

    if target_idx <= last_applied_idx:
        print(f"  {os.path.basename(run_dir)}: variant idx {last_applied_idx} already active ({hours:.1f}h elapsed) — skip")
        return

    target_variant = variants[target_idx]
    variant_id = target_variant.get("id", "?")
    thumb_file = target_variant.get("output_file", "")
    thumb_path = os.path.join(run_dir, thumb_file)

    if not thumb_file or not os.path.exists(thumb_path):
        print(f"  {os.path.basename(run_dir)}: thumbnail file missing for variant {variant_id} — skip")
        return

    print(f"  {os.path.basename(run_dir)}: {hours:.1f}h elapsed → swapping to variant {variant_id} ({thumb_file})")

    if dry_run:
        print(f"    [DRY RUN] would call thumbnails().set(videoId={youtube_video_id})")
        return

    try:
        yt = _get_youtube_client()
        yt.thumbnails().set(
            videoId=youtube_video_id,
            media_body=MediaFileUpload(thumb_path, mimetype="image/png"),
        ).execute()
        print(f"    Thumbnail set ✅ (variant {variant_id})")
    except Exception as exc:
        print(f"    thumbnails().set failed: {exc}")
        return

    swap_log.append({
        "swapped_at": _now_iso(),
        "variant_id": variant_id,
        "variant_index": target_idx,
        "hours_elapsed": round(hours, 1),
        "youtube_video_id": youtube_video_id,
        "thumb_file": thumb_file,
    })
    _save(swap_log, swap_log_path)


def main():
    parser = argparse.ArgumentParser(description="A/B Thumbnail Rotation Tool")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without calling YouTube API")
    parser.add_argument("--run-dir", default="", help="Process a single run dir instead of scanning workspace/")
    args = parser.parse_args()

    print(f"\n{'=' * 52}")
    print(f" A/B Thumbnail Swap {'[DRY RUN] ' if args.dry_run else ''}")
    print(f"{'=' * 52}")

    if args.run_dir:
        run_dirs = [args.run_dir]
    else:
        run_dirs = _find_eligible_runs(WORKSPACE)

    if not run_dirs:
        print("  No eligible runs found.")
        return

    print(f"  Found {len(run_dirs)} eligible run(s)\n")
    for run_dir in run_dirs:
        process_run(run_dir, dry_run=args.dry_run)

    print(f"\n{'=' * 52}")
    print(" Done.")
    print(f"{'=' * 52}\n")


if __name__ == "__main__":
    main()
