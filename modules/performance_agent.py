from __future__ import annotations

import os
from datetime import datetime, timedelta

from utils.helpers import load_json, save_json, now_iso

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None


METRICS_PRIMARY = [
    "views",
    "engagedViews",
    "averageViewDuration",
    "averageViewPercentage",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
]

METRIC_FALLBACKS = [
    METRICS_PRIMARY,
    ["views", "averageViewDuration", "averageViewPercentage", "likes", "comments", "shares", "subscribersGained"],
    ["views", "averageViewDuration", "likes", "comments", "shares", "subscribersGained"],
    ["views", "likes", "comments", "shares", "subscribersGained"],
]


def _youtube_analytics_client():
    if Credentials is None:
        raise RuntimeError("google-api-python-client not installed")
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    )
    creds.refresh(Request())
    return build("youtubeAnalytics", "v2", credentials=creds)


def _load_uploaded_topic_entries(memory_file: str, lookback_days: int) -> list[dict]:
    if not os.path.exists(memory_file):
        return []
    data = load_json(memory_file)
    if not isinstance(data, list):
        return []
    cutoff = datetime.utcnow().date() - timedelta(days=lookback_days)
    entries = []
    for entry in data:
        youtube_id = entry.get("youtube_video_id")
        if not youtube_id or youtube_id == "MOCK_NOT_UPLOADED":
            continue
        try:
            published = datetime.strptime(entry.get("published_date", ""), "%Y-%m-%d").date()
        except ValueError:
            published = cutoff
        if published >= cutoff:
            entries.append(entry)
    return entries


def _query_metrics(client, video_ids: list[str], start_date: str, end_date: str) -> tuple[list[str], list[list]]:
    last_error = None
    for metrics in METRIC_FALLBACKS:
        try:
            response = client.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics=",".join(metrics),
                dimensions="video",
                filters=f"video=={','.join(video_ids)}",
                maxResults=len(video_ids),
            ).execute()
            headers = [h["name"] for h in response.get("columnHeaders", [])]
            return headers, response.get("rows", [])
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(f"YouTube Analytics query failed: {last_error}")


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _score(metrics: dict) -> float:
    views = _as_float(metrics.get("views"))
    engaged = _as_float(metrics.get("engagedViews"))
    avg_pct = _as_float(metrics.get("averageViewPercentage"))
    likes = _as_float(metrics.get("likes"))
    comments = _as_float(metrics.get("comments"))
    shares = _as_float(metrics.get("shares"))
    subs = _as_float(metrics.get("subscribersGained"))
    retention_bonus = views * max(0.0, min(avg_pct, 200.0)) / 100.0
    return round(views + engaged * 2 + retention_bonus + likes * 20 + comments * 35 + shares * 30 + subs * 100, 2)


def run_performance_sync(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[performance] Syncing YouTube Analytics feedback for {video_id}")
    memory_file = config.get("topic_memory_file", "topic_memory_soft_reset.json")
    performance_file = config.get("performance_memory_file", "performance_memory_soft_reset.json")
    lookback_days = int(config.get("performance_lookback_days", 45))
    output_path = os.path.join(run_dir, "00_performance_sync.json")

    result = {
        "video_id": video_id,
        "status": "skipped",
        "reason": "",
        "videos_synced": 0,
        "generated_at": now_iso(),
    }

    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    if any(not os.environ.get(key) for key in required):
        result["reason"] = "missing_youtube_oauth"
        save_json(result, output_path)
        print("[performance] Skipped: missing YouTube OAuth")
        return result

    entries = _load_uploaded_topic_entries(memory_file, lookback_days)
    if not entries:
        result["reason"] = "no_uploaded_videos_in_memory"
        save_json(result, output_path)
        print("[performance] Skipped: no uploaded videos in topic memory")
        return result

    today = datetime.utcnow().date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=lookback_days)
    if start > end:
        result["reason"] = "date_window_not_ready"
        save_json(result, output_path)
        return result

    try:
        client = _youtube_analytics_client()
        ids = [entry["youtube_video_id"] for entry in entries][:500]
        headers, rows = _query_metrics(client, ids, start.isoformat(), end.isoformat())
        by_id = {}
        for row in rows:
            mapped = dict(zip(headers, row))
            video_key = mapped.pop("video", "")
            by_id[video_key] = mapped

        videos = []
        for entry in entries:
            metrics = by_id.get(entry["youtube_video_id"], {})
            record = {
                **entry,
                "metrics": metrics,
                "performance_score": _score(metrics),
            }
            videos.append(record)

        videos.sort(key=lambda item: item.get("performance_score", 0), reverse=True)
        memory = {
            "generated_at": now_iso(),
            "lookback_days": lookback_days,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "videos": videos,
        }
        save_json(memory, performance_file)

        result.update({
            "status": "ok",
            "reason": "",
            "videos_synced": len(videos),
            "performance_memory_file": performance_file,
        })
        save_json(result, output_path)
        print(f"[performance] Done. Synced {len(videos)} video(s)")
        return result
    except Exception as exc:
        result["status"] = "soft_failed"
        result["reason"] = str(exc)
        save_json(result, output_path)
        print(f"[performance] Soft-failed: {exc}")
        return result


def run_performance_sync_mock(video_id: str, run_dir: str, config: dict) -> dict:
    result = {
        "video_id": video_id,
        "status": "mock_skipped",
        "videos_synced": 0,
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "00_performance_sync.json"))
    return result
