from __future__ import annotations

import os
import math
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


def _load_performance_memory(performance_file: str) -> dict:
    if not os.path.exists(performance_file):
        return {"videos": []}
    data = load_json(performance_file)
    return data if isinstance(data, dict) else {"videos": []}


def _parse_date(value: str) -> datetime.date | None:
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def _cache_by_video_id(performance_file: str) -> dict[str, dict]:
    memory = _load_performance_memory(performance_file)
    cached = {}
    for record in memory.get("videos", []):
        youtube_id = record.get("youtube_video_id")
        if youtube_id:
            cached[youtube_id] = record
    return cached


def _should_reuse_cached(record: dict | None, refresh_days: int) -> bool:
    if not record:
        return False
    fetched_at = _parse_iso(record.get("analytics_fetched_at", ""))
    if not fetched_at:
        return False
    return fetched_at >= datetime.utcnow() - timedelta(days=refresh_days)


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


def _rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _score(metrics: dict) -> dict:
    views = _as_float(metrics.get("views"))
    engaged = _as_float(metrics.get("engagedViews"))
    avg_pct = _as_float(metrics.get("averageViewPercentage"))
    likes = _as_float(metrics.get("likes"))
    comments = _as_float(metrics.get("comments"))
    shares = _as_float(metrics.get("shares"))
    subs = _as_float(metrics.get("subscribersGained"))
    weighted_engagement = likes + comments * 3 + shares * 4 + subs * 8

    hold_score = max(0.0, min(avg_pct, 200.0))
    hook_score = min(_rate(engaged, views), 1.5) * 100.0
    resonance_per_engaged = _rate(weighted_engagement, max(engaged, 1.0))
    resonance_per_view = _rate(weighted_engagement, max(views, 1.0))
    resonance_score = min(resonance_per_engaged * 100.0, 200.0)
    # Subscriber conversion: subs per 1000 views, scaled so 2.0/1000 = 100 (industry avg for content Shorts)
    conversion_rate = _rate(subs, max(views, 1.0)) * 1000.0
    conversion_score = min(conversion_rate / 2.0 * 100.0, 100.0)
    reach_score = min(math.log10(max(views, 0.0) + 1.0) * 25.0, 100.0)
    composite_score = (
        hold_score        * 0.35
        + hook_score      * 0.25
        + resonance_score * 0.20
        + conversion_score * 0.15
        + reach_score     * 0.05
    )
    return {
        "composite_score": round(composite_score, 2),
        "performance_score": round(composite_score, 2),
        "hook_score": round(hook_score, 2),
        "hold_score": round(hold_score, 2),
        "resonance_score": round(resonance_score, 2),
        "resonance_per_engaged": round(resonance_per_engaged, 4),
        "resonance_per_view": round(resonance_per_view, 4),
        "conversion_score": round(conversion_score, 2),
        "conversion_rate_per_1k": round(conversion_rate, 4),
        "reach_score": round(reach_score, 2),
    }


def _enrich_from_workspace(video_id: str) -> dict:
    """
    Read hook_text, content_format, and title_text from run workspace outputs.
    These fields power the self-improvement learning loop.
    Returns empty dict if workspace outputs don't exist.
    """
    run_dir = os.path.join("workspace", f"run_{video_id}")
    extra = {}

    script_path = os.path.join(run_dir, "02_script.json")
    long_script_path = os.path.join(run_dir, "02_longform_script.json")
    if os.path.exists(script_path) or os.path.exists(long_script_path):
        try:
            script = load_json(script_path if os.path.exists(script_path) else long_script_path)
            extra["hook_text"]      = script.get("hook", "")
            extra["content_format"] = script.get("content_format", script.get("narrative_format", ""))
            extra["editorial_pov"]  = script.get("editorial_pov", "")
        except Exception:
            pass

    metadata_path = os.path.join(run_dir, "07_metadata.json")
    long_metadata_path = os.path.join(run_dir, "03_longform_metadata.json")
    if os.path.exists(metadata_path) or os.path.exists(long_metadata_path):
        try:
            meta = load_json(metadata_path if os.path.exists(metadata_path) else long_metadata_path)
            extra["title_text"] = meta.get("title", "")
            extra["title_type"] = ""   # future: auto-tagged in creative judge
        except Exception:
            pass

    judge_path = os.path.join(run_dir, "10_judge_report.json")
    if os.path.exists(judge_path):
        try:
            judge = load_json(judge_path)
            extra["tone_type"] = judge.get("tone_type", "")
        except Exception:
            pass

    return extra


def _build_record(entry: dict, metrics: dict, fetched_at: str, today: datetime.date) -> dict:
    published = _parse_date(entry.get("published_date", "")) or today
    score_parts = _score(metrics)
    workspace_extras = _enrich_from_workspace(entry.get("video_id", ""))
    return {
        **entry,
        "metrics": metrics,
        **score_parts,
        "analytics_fetched_at": fetched_at,
        "analytics_days_old": max(0, (today - published).days),
        **workspace_extras,
    }


def run_performance_sync(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[performance] Syncing YouTube Analytics feedback for {video_id}")
    memory_file = config.get("topic_memory_file", "topic_memory_soft_reset.json")
    performance_file = config.get("performance_memory_file", "performance_memory_soft_reset.json")
    lookback_days = int(config.get("performance_lookback_days", 45))
    min_age_days = int(config.get("performance_min_video_age_days", 2))
    refresh_days = int(config.get("performance_refresh_interval_days", 7))
    output_path = os.path.join(run_dir, "00_performance_sync.json")

    result = {
        "video_id": video_id,
        "status": "skipped",
        "reason": "",
        "videos_synced": 0,
        "videos_reused": 0,
        "videos_too_new": 0,
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
        today_iso = now_iso()
        cached = _cache_by_video_id(performance_file)
        fresh_records = []
        entries_to_fetch = []
        too_new = 0

        for entry in entries:
            youtube_id = entry["youtube_video_id"]
            published = _parse_date(entry.get("published_date", "")) or today
            age_days = (today - published).days
            cached_record = cached.get(youtube_id)

            if age_days < min_age_days:
                too_new += 1
                if cached_record:
                    fresh_records.append(cached_record)
                continue

            if _should_reuse_cached(cached_record, refresh_days):
                fresh_records.append(cached_record)
                continue

            entries_to_fetch.append(entry)

        by_id = {}
        headers = []
        if entries_to_fetch:
            client = _youtube_analytics_client()
            ids = [entry["youtube_video_id"] for entry in entries_to_fetch][:500]
            headers, rows = _query_metrics(client, ids, start.isoformat(), end.isoformat())
            for row in rows:
                mapped = dict(zip(headers, row))
                video_key = mapped.pop("video", "")
                by_id[video_key] = mapped

        videos = []
        videos.extend(fresh_records)
        for entry in entries_to_fetch:
            metrics = by_id.get(entry["youtube_video_id"], {})
            videos.append(_build_record(entry, metrics, today_iso, today))

        videos.sort(key=lambda item: item.get("composite_score", item.get("performance_score", 0)), reverse=True)
        memory = {
            "generated_at": now_iso(),
            "lookback_days": lookback_days,
            "min_video_age_days": min_age_days,
            "refresh_interval_days": refresh_days,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "videos": videos,
        }
        save_json(memory, performance_file)

        result.update({
            "status": "ok",
            "reason": "",
            "videos_synced": len(videos),
            "videos_reused": len(fresh_records),
            "videos_fetched": len(entries_to_fetch),
            "videos_too_new": too_new,
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
