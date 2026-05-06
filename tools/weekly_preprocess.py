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
        pub = v.get("published_at", "")
        if not pub:
            continue
        try:
            dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
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
    top_performers, bottom_performers = _identify_top_bottom(strategy_eligible)

    output = {
        "week": week_label,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(videos),
        "strategy_eligible_videos": len(strategy_eligible),
        "channel_trend_4weeks": trend,
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
