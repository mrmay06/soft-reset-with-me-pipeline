"""
Weekly Analytics Fetch
======================
Pulls YouTube Analytics data for all published videos.
Respects a 48-hour maturity gate and per-track minimum view thresholds.
Writes strategy/analytics_cache/YYYY-WW.json.

Usage:
    python tools/weekly_analytics_fetch.py
    python tools/weekly_analytics_fetch.py --week 2026-W20   # re-fetch a specific week
    python tools/weekly_analytics_fetch.py --dry-run         # print what would be fetched
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

MATURITY_DAYS = 2
DEFAULT_MIN_VIEWS = 200
ANALYTICS_CACHE_DIR = "strategy/analytics_cache"

METRICS = [
    "views",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
    "estimatedMinutesWatched",
    "averageViewDuration",
    "averageViewPercentage",
    "impressions",
    "impressionClickThroughRate",
]


def _get_youtube_client():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from google.auth.exceptions import RefreshError
    except ImportError:
        raise RuntimeError("google-api-python-client not installed")

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl",
                "https://www.googleapis.com/auth/yt-analytics.readonly"],
    )
    try:
        creds.refresh(Request())
    except RefreshError as exc:
        raise RuntimeError("YouTube refresh token expired. Run tools/get_youtube_token.py.") from exc

    data_client = build("youtube", "v3", credentials=creds)
    analytics_client = build("youtubeAnalytics", "v2", credentials=creds)
    return data_client, analytics_client


def _get_channel_id(data_client) -> str:
    resp = data_client.channels().list(part="id", mine=True).execute()
    return resp["items"][0]["id"]


def _load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _memory_sources() -> list[tuple[str, str, dict]]:
    shorts_config = _load_json("config/pipeline_config.json", {})
    longform_config = _load_json("config/longform_config.json", {})
    return [
        (shorts_config.get("topic_memory_file", "topic_memory_soft_reset.json"), "shorts", shorts_config),
        (longform_config.get("topic_memory_file", "topic_memory_soft_reset_long.json"), "longform", longform_config),
    ]


def _collect_video_ids() -> list[dict]:
    """
    Collect all published YouTube video IDs from topic memory files.
    Returns list of dicts with video_id, youtube_video_id, published_at, track.
    """
    entries = []
    for fname, track, track_config in _memory_sources():
        if not os.path.exists(fname):
            continue
        try:
            with open(fname) as f:
                memory = json.load(f)
            if not isinstance(memory, list):
                continue
            for entry in memory:
                yt_id = entry.get("youtube_video_id")
                if yt_id and yt_id not in ("MOCK_NOT_UPLOADED", "", None):
                    entries.append({
                        "video_id": entry.get("video_id", ""),
                        "youtube_video_id": yt_id,
                        "youtube_url": entry.get("youtube_url", ""),
                        "published_at": entry.get("published_at") or entry.get("uploaded_at") or entry.get("published_date", ""),
                        "track": track,
                        "title": entry.get("title", ""),
                        "traits": entry.get("judge_traits", {}),
                        "composite_score": entry.get("judge_composite_score"),
                        "experiment_label": entry.get("experiment_label", "baseline"),
                        "experiment_id": entry.get("experiment_id"),
                        "strategy_version": entry.get("strategy_version", "untracked"),
                        "min_views_for_strategy": int(track_config.get("performance_min_views", DEFAULT_MIN_VIEWS)),
                    })
        except Exception as e:
            print(f"[analytics_fetch] Warning: could not read {fname}: {e}")
    return entries


def _is_mature(published_at: str) -> bool:
    if not published_at:
        return False
    try:
        if "T" in published_at:
            pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        else:
            pub = datetime.strptime(published_at[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - pub).days >= MATURITY_DAYS
    except Exception:
        return False


def _fetch_video_analytics(analytics_client, youtube_video_id: str, channel_id: str) -> dict | None:
    """Fetch aggregate metrics for a single video via YouTube Analytics API."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=365)

    try:
        resp = analytics_client.reports().query(
            ids=f"channel=={channel_id}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics=",".join(METRICS),
            filters=f"video=={youtube_video_id}",
            dimensions="video",
        ).execute()

        rows = resp.get("rows", [])
        if not rows:
            return None

        col_headers = [h["name"] for h in resp.get("columnHeaders", [])]
        row = rows[0]
        result = {col_headers[i]: row[i] for i in range(len(col_headers)) if col_headers[i] != "video"}
        return result
    except Exception as e:
        print(f"[analytics_fetch] Could not fetch analytics for {youtube_video_id}: {e}")
        return None


def _fetch_retention_curve(analytics_client, youtube_video_id: str, channel_id: str) -> dict | None:
    """Fetch audience retention curve for a single video. Used for top/bottom performers only."""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=365)
    try:
        resp = analytics_client.reports().query(
            ids=f"channel=={channel_id}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="audienceWatchRatio,relativeRetentionPerformance",
            filters=f"video=={youtube_video_id}",
            dimensions="elapsedVideoTimeRatio",
        ).execute()
        return resp
    except Exception as e:
        print(f"[analytics_fetch] Retention curve unavailable for {youtube_video_id}: {e}")
        return None


def _get_judge_report(youtube_video_id: str, workspace_dir: str = "workspace") -> dict:
    """Find and return the judge report for a given youtube_video_id."""
    import glob
    for run_dir in glob.glob(os.path.join(workspace_dir, "run_*")):
        judge_path = os.path.join(run_dir, "10_judge_report.json")
        if os.path.exists(judge_path):
            try:
                with open(judge_path) as f:
                    report = json.load(f)
                if report.get("youtube_video_id") == youtube_video_id:
                    return report
            except Exception:
                pass
    return {}


def run_fetch(week_label: str | None = None, dry_run: bool = False) -> str:
    """
    Main fetch function. Returns path to written cache file.
    """
    if week_label is None:
        today = datetime.now(timezone.utc)
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

    os.makedirs(ANALYTICS_CACHE_DIR, exist_ok=True)
    output_path = os.path.join(ANALYTICS_CACHE_DIR, f"{week_label}.json")

    all_entries = _collect_video_ids()
    mature_entries = [e for e in all_entries if _is_mature(e["published_at"])]

    print(f"\n[analytics_fetch] Week: {week_label}")
    print(f"[analytics_fetch] Total published videos found: {len(all_entries)}")
    print(f"[analytics_fetch] Mature ({MATURITY_DAYS}+ days old): {len(mature_entries)}")

    if dry_run:
        for e in mature_entries:
            print(f"  Would fetch: {e['youtube_video_id']} — {e['title'][:50]}")
        print("[analytics_fetch] Dry-run complete. No data written.")
        return output_path

    data_client, analytics_client = _get_youtube_client()
    channel_id = _get_channel_id(data_client)
    print(f"[analytics_fetch] Channel ID: {channel_id}")

    results = []
    skipped_low_views = 0

    for entry in mature_entries:
        yt_id = entry["youtube_video_id"]
        metrics = _fetch_video_analytics(analytics_client, yt_id, channel_id)
        if metrics is None:
            print(f"  {yt_id}: no data")
            continue

        views = int(metrics.get("views", 0))
        min_views = int(entry.get("min_views_for_strategy", DEFAULT_MIN_VIEWS))
        if views < min_views:
            skipped_low_views += 1
            print(f"  {yt_id}: {views} views — below {entry['track']} threshold ({min_views}), excluded from strategy analysis")
            metrics["excluded_from_strategy"] = True
        else:
            metrics["excluded_from_strategy"] = False

        judge = _get_judge_report(yt_id)

        record = {
            **entry,
            "analytics": metrics,
            "traits": judge.get("traits") or entry.get("traits", {}),
            "composite_score": judge.get("composite_score", entry.get("composite_score")),
            "experiment_label": judge.get("experiment_label", entry.get("experiment_label", "baseline")),
            "experiment_id": judge.get("experiment_id", entry.get("experiment_id")),
            "strategy_version": judge.get("strategy_version", entry.get("strategy_version", "untracked")),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        results.append(record)
        avg_pct = float(metrics.get("averageViewPercentage", 0) or 0)
        print(f"  {yt_id}: {views:,} views, {avg_pct:.1f}% retention")

    cache = {
        "week": week_label,
        "channel_id": channel_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(results),
        "skipped_low_views": skipped_low_views,
        "videos": results,
    }

    with open(output_path, "w") as f:
        json.dump(cache, f, indent=2)

    print(f"\n[analytics_fetch] Done. {len(results)} videos written to {output_path}")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly Analytics Fetch")
    parser.add_argument("--week", default=None, help="ISO week label e.g. 2026-W20")
    parser.add_argument("--dry-run", action="store_true", help="Preview without fetching")
    args = parser.parse_args()
    run_fetch(week_label=args.week, dry_run=args.dry_run)
