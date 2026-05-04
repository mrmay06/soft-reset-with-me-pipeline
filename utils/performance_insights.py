from __future__ import annotations

import os
from collections import defaultdict

from utils.helpers import load_json


def _safe_num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def load_performance_memory(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def _metrics(video: dict) -> dict:
    metrics = video.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}


def _views(video: dict) -> int:
    return _safe_int(_metrics(video).get("views"))


def _engaged(video: dict) -> int:
    return _safe_int(_metrics(video).get("engagedViews"))


def _avg_pct(video: dict) -> float:
    return _safe_num(_metrics(video).get("averageViewPercentage"))


def _composite(video: dict) -> float:
    return _safe_num(video.get("composite_score", video.get("performance_score")))


def _valid_with_analytics(video: dict) -> bool:
    return bool(video.get("youtube_video_id") and _metrics(video))


def _valid_for_patterns(video: dict, min_views: int) -> bool:
    return _valid_with_analytics(video) and _views(video) >= min_views and _avg_pct(video) > 0


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _bucket_average(videos: list[dict], key: str, metric_fn) -> list[tuple[str, float, int]]:
    buckets = defaultdict(list)
    for video in videos:
        label = str(video.get(key, "") or "unknown").strip().lower()
        if label:
            buckets[label].append(metric_fn(video))
    rows = [(label, _avg(values), len(values)) for label, values in buckets.items() if values]
    return sorted(rows, key=lambda item: item[1], reverse=True)


def _score_calibration(videos: list[dict]) -> str:
    high = [v for v in videos if _safe_num(v.get("total_score")) >= 18]
    mid = [v for v in videos if 14 <= _safe_num(v.get("total_score")) < 18]
    low = [v for v in videos if 0 < _safe_num(v.get("total_score")) < 14]
    parts = []
    if high:
        parts.append(f"score >=18: {round(_avg([_composite(v) for v in high]), 1)} composite ({len(high)} videos)")
    if mid:
        parts.append(f"score 14-17: {round(_avg([_composite(v) for v in mid]), 1)} composite ({len(mid)} videos)")
    if low:
        parts.append(f"score <14: {round(_avg([_composite(v) for v in low]), 1)} composite ({len(low)} videos)")
    return " | ".join(parts) if parts else "not enough scored videos yet"


def _line(video: dict) -> str:
    m = _metrics(video)
    hook_rate = 0.0
    views = _views(video)
    engaged = _engaged(video)
    if views > 0:
        hook_rate = min(engaged / views, 1.5) * 100
    resonance = _safe_num(video.get("resonance_per_engaged")) * 100
    return (
        f"{video.get('content_format', 'unknown')} | {video.get('category', 'unknown')} | "
        f"hook: {str(video.get('hook', ''))[:80]} | "
        f"composite {round(_composite(video), 1)}, "
        f"views {views}, engaged {engaged}, hook {round(hook_rate, 1)}%, "
        f"APV {round(_avg_pct(video), 1)}%, resonance {round(resonance, 1)}%, "
        f"likes {_safe_int(m.get('likes'))}, comments {_safe_int(m.get('comments'))}, "
        f"shares {_safe_int(m.get('shares'))}, subs+ {_safe_int(m.get('subscribersGained'))}"
    )


def _format_bucket_rows(rows: list[tuple[str, float, int]], limit: int = 4) -> str:
    if not rows:
        return "none yet"
    return " | ".join(f"{label}: {round(avg, 1)}% ({count})" for label, avg, count in rows[:limit])


def summarize_performance_for_prompt(
    path: str,
    min_videos: int = 8,
    pattern_min_videos: int = 25,
    min_views: int = 50,
) -> str:
    """Return staged feedback: collect early, infer patterns only after enough data."""
    memory = load_performance_memory(path)
    videos = [v for v in memory.get("videos", []) if isinstance(v, dict)]
    analytics_videos = [v for v in videos if _valid_with_analytics(v)]
    pattern_videos = [v for v in analytics_videos if _valid_for_patterns(v, min_views)]

    if not analytics_videos:
        return (
            "No reliable performance data yet. Do not optimize from analytics. "
            "Prioritize brand rules, topic diversity, specific lived moments, and strong first-second hooks."
        )

    top_examples = sorted(analytics_videos, key=_composite, reverse=True)[:5]
    weak_examples = sorted(analytics_videos, key=_composite)[:3]

    if len(pattern_videos) < min_videos:
        return "\n".join([
            f"Analytics stage: COLLECTING. {len(analytics_videos)} video(s) have analytics; "
            f"{len(pattern_videos)} meet the {min_views}+ view noise filter.",
            "Use this only as weak signal. Do not boost categories, do not suppress categories, and do not repeat exact topics.",
            "Early examples to inspect:",
            *[f"- {_line(v)}" for v in top_examples[:3]],
            "Instruction: keep testing different pillars and formats while improving hook clarity and pacing.",
        ])

    if len(pattern_videos) < pattern_min_videos:
        return "\n".join([
            f"Analytics stage: EXAMPLE-LEVEL. {len(pattern_videos)} valid video(s) meet {min_views}+ views; "
            f"wait for {pattern_min_videos}+ before strong category/format conclusions.",
            "Use individual winners as directional examples, not proof that a whole category is best.",
            "Top examples:",
            *[f"- {_line(v)}" for v in top_examples],
            "Weak examples:",
            *[f"- {_line(v)}" for v in weak_examples],
            "Instruction: adapt winning hook shapes, emotional specificity, and pacing. Do not copy exact hooks or topics.",
        ])

    category_rows = _bucket_average(pattern_videos, "category", _avg_pct)
    format_rows = _bucket_average(pattern_videos, "content_format", _avg_pct)
    angle_rows = _bucket_average(pattern_videos, "angle_type", _avg_pct)
    hook_quality_rows = _bucket_average(pattern_videos, "hook_quality", _avg_pct)

    category_weak = list(reversed(category_rows))[:4]
    format_weak = list(reversed(format_rows))[:4]

    return "\n".join([
        f"Analytics stage: PATTERN-LEVEL. {len(pattern_videos)} valid videos analyzed with {min_views}+ views.",
        f"Best APV by category: {_format_bucket_rows(category_rows)}",
        f"Weak APV by category: {_format_bucket_rows(category_weak)}",
        f"Best APV by format: {_format_bucket_rows(format_rows)}",
        f"Weak APV by format: {_format_bucket_rows(format_weak)}",
        f"Best APV by angle: {_format_bucket_rows(angle_rows)}",
        f"Hook quality APV: {_format_bucket_rows(hook_quality_rows)}",
        f"Research-score calibration: {_score_calibration(pattern_videos)}",
        "Top individual examples:",
        *[f"- {_line(v)}" for v in top_examples[:5]],
        "Instruction: lean toward patterns with stronger hook rate, APV, and resonance. Avoid weak patterns unless the new topic is much more specific. Never repeat exact topics or hooks.",
    ])
