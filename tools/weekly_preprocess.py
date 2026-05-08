"""
Weekly Preprocess
=================
Reads the latest analytics cache, groups videos by creative trait dimensions,
and computes per-group averages. Produces a structured comparison JSON that
the AI analysis step can reason about without seeing raw individual numbers.

Usage:
    python tools/weekly_preprocess.py
    python tools/weekly_preprocess.py --week 2026-W20
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ANALYTICS_CACHE_DIR = "strategy/analytics_cache"
COMPARISONS_DIR = "strategy/comparisons"
STRATEGY_FILE = "strategy/strategy_memory.json"

TRAIT_DIMENSIONS = [
    "hook_type",
    "angle_type",
    "category",
    "title_type",
    "visual_style_mix",
    "thumbnail_type",
    "video_length_band",
    "narrative_format",
    "character_used",
    "experiment_label",
]

PERFORMANCE_METRICS = [
    "views",
    "averageViewPercentage",
    "averageViewDuration",
    "impressionClickThroughRate",
    "likes",
    "comments",
    "shares",
    "subscribersGained",
    "subscribersLost",
]

DERIVED_METRICS = [
    "likes_per_view",
    "comments_per_view",
    "shares_per_view",
    "subs_per_view",
]


def _safe_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _compute_derived(analytics: dict) -> dict:
    views = _safe_float(analytics.get("views")) or 0
    result = {}
    if views > 0:
        result["likes_per_view"] = (_safe_float(analytics.get("likes")) or 0) / views
        result["comments_per_view"] = (_safe_float(analytics.get("comments")) or 0) / views
        result["shares_per_view"] = (_safe_float(analytics.get("shares")) or 0) / views
        result["subs_per_view"] = (_safe_float(analytics.get("subscribersGained")) or 0) / views
    return result


def _group_by_trait(videos: list[dict]) -> dict[str, dict[str, list[dict]]]:
    """Group videos by each trait dimension."""
    groups: dict[str, dict[str, list[dict]]] = {dim: defaultdict(list) for dim in TRAIT_DIMENSIONS}
    for v in videos:
        if v.get("analytics", {}).get("excluded_from_strategy"):
            continue
        traits = v.get("traits", {})
        for dim in TRAIT_DIMENSIONS:
            val = traits.get(dim) or v.get(dim) or "unknown"
            groups[dim][val].append(v)
    return groups


def _avg(values: list[float]) -> float | None:
    valid = [v for v in values if v is not None]
    return round(sum(valid) / len(valid), 4) if valid else None


def _summarize_group(videos: list[dict]) -> dict:
    all_analytics = [v.get("analytics", {}) for v in videos]
    derived_list = [_compute_derived(a) for a in all_analytics]

    summary: dict = {"count": len(videos)}
    for metric in PERFORMANCE_METRICS:
        vals = [_safe_float(a.get(metric)) for a in all_analytics]
        summary[f"avg_{metric}"] = _avg(vals)

    for metric in DERIVED_METRICS:
        vals = [d.get(metric) for d in derived_list]
        summary[f"avg_{metric}"] = _avg([v for v in vals if v is not None])

    scores = [v.get("composite_score") for v in videos if v.get("composite_score")]
    summary["avg_judge_composite"] = _avg(scores)

    top = sorted(videos, key=lambda v: _safe_float(v.get("analytics", {}).get("views")) or 0, reverse=True)
    summary["top_titles"] = [v.get("title", "")[:60] for v in top[:3]]

    return summary


def _compute_channel_trend(videos: list[dict]) -> dict:
    """Week-over-week trend signal on key metrics."""
    by_week: dict[str, list[dict]] = defaultdict(list)
    for v in videos:
        pub = v.get("published_at") or v.get("published_date", "")
        if not pub:
            continue
        try:
            if "T" in pub:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(pub[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            iso = dt.isocalendar()
            week_key = f"{iso[0]}-W{iso[1]:02d}"
            by_week[week_key].append(v)
        except Exception:
            pass

    trend = {}
    for week_key in sorted(by_week.keys())[-4:]:
        vids = by_week[week_key]
        analytics_list = [v.get("analytics", {}) for v in vids]
        trend[week_key] = {
            "videos": len(vids),
            "avg_retention": _avg([_safe_float(a.get("averageViewPercentage")) for a in analytics_list]),
            "avg_ctr": _avg([_safe_float(a.get("impressionClickThroughRate")) for a in analytics_list]),
            "avg_views": _avg([_safe_float(a.get("views")) for a in analytics_list]),
        }
    return trend


def _comments_per_view(videos: list[dict]) -> float | None:
    views = sum(_safe_float(v.get("analytics", {}).get("views")) or 0 for v in videos)
    comments = sum(_safe_float(v.get("analytics", {}).get("comments")) or 0 for v in videos)
    if views <= 0:
        return None
    return round(comments / views, 6)


def _compute_channel_health(trend: dict, videos: list[dict]) -> dict:
    """Return a bounded 0-120 health score anchored to prior weeks when possible."""
    if not videos:
        return {"score": None, "status": "no eligible videos"}

    weeks = sorted(trend.keys())
    current_week = weeks[-1] if weeks else None
    previous_weeks = weeks[:-1]
    current = trend.get(current_week, {}) if current_week else {}
    previous = [trend[w] for w in previous_weeks if trend.get(w)]

    def avg(items: list[dict], key: str) -> float | None:
        vals = [_safe_float(item.get(key)) for item in items]
        vals = [v for v in vals if v is not None and v > 0]
        return round(sum(vals) / len(vals), 4) if vals else None

    current_ret = _safe_float(current.get("avg_retention"))
    current_ctr = _safe_float(current.get("avg_ctr"))
    def video_week(video: dict) -> str | None:
        pub = video.get("published_at") or video.get("published_date", "")
        if not pub:
            return None
        try:
            if "T" in pub:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            else:
                dt = datetime.strptime(pub[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            iso = dt.isocalendar()
            return f"{iso[0]}-W{iso[1]:02d}"
        except Exception:
            return None

    current_week_videos = [v for v in videos if video_week(v) == current_week]
    current_cpv = _comments_per_view(current_week_videos) or _comments_per_view(videos)

    baseline_ret = avg(previous, "avg_retention")
    baseline_ctr = avg(previous, "avg_ctr")
    baseline_cpv = _comments_per_view(videos)

    if not baseline_ret or not baseline_ctr or not baseline_cpv:
        return {
            "score": None,
            "status": "insufficient baseline",
            "current_week": current_week,
            "current_retention": current_ret,
            "current_ctr": current_ctr,
            "comments_per_view": current_cpv,
        }

    score = (
        min((current_ret or 0) / baseline_ret, 1.5) * 0.4
        + min((current_ctr or 0) / baseline_ctr, 1.5) * 0.3
        + min((current_cpv or 0) / baseline_cpv, 1.5) * 0.3
    ) * 100
    return {
        "score": round(score, 1),
        "current_week": current_week,
        "baseline_weeks": previous_weeks,
        "current_retention": current_ret,
        "baseline_retention": baseline_ret,
        "current_ctr": current_ctr,
        "baseline_ctr": baseline_ctr,
        "current_comments_per_view": current_cpv,
        "baseline_comments_per_view": baseline_cpv,
    }


def _summarize_experiments(videos: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for video in videos:
        experiment_id = video.get("experiment_id")
        if experiment_id:
            buckets[str(experiment_id)].append(video)
    outcomes = []
    for experiment_id, items in sorted(buckets.items()):
        summary = _summarize_group(items)
        outcomes.append({
            "experiment_id": experiment_id,
            "count": len(items),
            "experiment_labels": sorted({str(v.get("experiment_label", "")) for v in items if v.get("experiment_label")}),
            "avg_retention": summary.get("avg_averageViewPercentage"),
            "avg_ctr": summary.get("avg_impressionClickThroughRate"),
            "avg_comments_per_view": summary.get("avg_comments_per_view"),
            "top_titles": summary.get("top_titles", []),
        })
    return outcomes


def _active_cooldowns(today: datetime) -> list[dict]:
    if not os.path.exists(STRATEGY_FILE):
        return []
    try:
        with open(STRATEGY_FILE) as f:
            strategy = json.load(f)
    except Exception:
        return []
    cooldowns = strategy.get("cooldowns", []) or strategy.get("research", {}).get("cooldowns", [])
    active = []
    today_date = today.date()
    for item in cooldowns if isinstance(cooldowns, list) else []:
        avoid_until = item.get("avoid_until") if isinstance(item, dict) else None
        try:
            until = datetime.strptime(str(avoid_until)[:10], "%Y-%m-%d").date()
        except Exception:
            until = None
        if until is None or until >= today_date:
            active.append(item)
    return active


def _identify_top_bottom(videos: list[dict], n: int = 2) -> tuple[list[dict], list[dict]]:
    """Return top N and bottom N videos by composite performance score."""
    eligible = [
        v for v in videos
        if not v.get("analytics", {}).get("excluded_from_strategy")
        and (_safe_float(v.get("analytics", {}).get("views")) or 0) >= 1
    ]

    def score(v: dict) -> float:
        a = v.get("analytics", {})
        retention = _safe_float(a.get("averageViewPercentage")) or 0
        ctr = _safe_float(a.get("impressionClickThroughRate")) or 0
        subs = _safe_float(a.get("subscribersGained")) or 0
        views = _safe_float(a.get("views")) or 1
        return retention * 0.4 + ctr * 10 * 0.3 + (subs / views * 1000) * 0.3

    ranked = sorted(eligible, key=score, reverse=True)
    return ranked[:n], ranked[-n:] if len(ranked) >= n * 2 else []


def run_preprocess(week_label: str | None = None) -> str:
    if week_label is None:
        today = datetime.now(timezone.utc)
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

    cache_path = os.path.join(ANALYTICS_CACHE_DIR, f"{week_label}.json")
    if not os.path.exists(cache_path):
        raise FileNotFoundError(
            f"No analytics cache for {week_label}. Run weekly_analytics_fetch.py first."
        )

    with open(cache_path) as f:
        cache = json.load(f)

    videos = cache.get("videos", [])
    strategy_eligible = [v for v in videos if not v.get("analytics", {}).get("excluded_from_strategy")]

    print(f"\n[preprocess] Week: {week_label}")
    print(f"[preprocess] Total videos: {len(videos)} | Strategy-eligible: {len(strategy_eligible)}")

    groups = _group_by_trait(strategy_eligible)
    comparisons: dict[str, dict] = {}
    for dim, dim_groups in groups.items():
        comparisons[dim] = {}
        for val, vids in sorted(dim_groups.items(), key=lambda x: -len(x[1])):
            comparisons[dim][val] = _summarize_group(vids)

    trend = _compute_channel_trend(strategy_eligible)
    channel_health = _compute_channel_health(trend, strategy_eligible)
    experiment_outcomes = _summarize_experiments(strategy_eligible)
    active_cooldowns = _active_cooldowns(datetime.now(timezone.utc))
    top_performers, bottom_performers = _identify_top_bottom(strategy_eligible)

    output = {
        "week": week_label,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(videos),
        "strategy_eligible_videos": len(strategy_eligible),
        "channel_trend_4weeks": trend,
        "channel_health_score": channel_health,
        "experiment_outcomes": experiment_outcomes,
        "active_cooldowns": active_cooldowns,
        "top_performers": [
            {
                "youtube_video_id": v.get("youtube_video_id"),
                "title": v.get("title", ""),
                "track": v.get("track"),
                "video_id": v.get("video_id"),
                "traits": v.get("traits", {}),
                "views": v.get("analytics", {}).get("views"),
                "retention": v.get("analytics", {}).get("averageViewPercentage"),
                "ctr": v.get("analytics", {}).get("impressionClickThroughRate"),
            }
            for v in top_performers
        ],
        "bottom_performers": [
            {
                "youtube_video_id": v.get("youtube_video_id"),
                "title": v.get("title", ""),
                "track": v.get("track"),
                "video_id": v.get("video_id"),
                "traits": v.get("traits", {}),
                "views": v.get("analytics", {}).get("views"),
                "retention": v.get("analytics", {}).get("averageViewPercentage"),
                "ctr": v.get("analytics", {}).get("impressionClickThroughRate"),
            }
            for v in bottom_performers
        ],
        "comparisons_by_trait": comparisons,
    }

    os.makedirs(COMPARISONS_DIR, exist_ok=True)
    output_path = os.path.join(COMPARISONS_DIR, f"{week_label}_comparison.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"[preprocess] Done. Written to {output_path}")

    for dim, groups_summary in comparisons.items():
        if len(groups_summary) >= 2:
            ranked = sorted(groups_summary.items(), key=lambda x: x[1].get("avg_averageViewPercentage") or 0, reverse=True)
            best_val, best = ranked[0]
            worst_val, worst = ranked[-1]
            best_ret = best.get("avg_averageViewPercentage")
            worst_ret = worst.get("avg_averageViewPercentage")
            if best_ret and worst_ret:
                print(
                    f"  {dim}: best={best_val} ({best_ret:.1f}% retention, n={best['count']}) "
                    f"vs worst={worst_val} ({worst_ret:.1f}%, n={worst['count']})"
                )

    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly Preprocess")
    parser.add_argument("--week", default=None, help="ISO week label e.g. 2026-W20")
    args = parser.parse_args()
    run_preprocess(week_label=args.week)
