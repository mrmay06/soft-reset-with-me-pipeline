from __future__ import annotations

import os

from utils.helpers import load_json


def _safe_num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_performance_memory(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def summarize_performance_for_prompt(path: str, min_videos: int = 8) -> str:
    """Return a compact prompt block. Stay conservative while data is sparse."""
    memory = load_performance_memory(path)
    videos = memory.get("videos", [])
    if not videos:
        return "No reliable performance data yet. Do not optimize from analytics."

    uploaded = [v for v in videos if v.get("youtube_video_id") and v.get("metrics")]
    if len(uploaded) < min_videos:
        return (
            f"Only {len(uploaded)} uploaded video(s) have analytics so far. "
            "Use this as weak signal only; keep prioritizing brand rules and topic diversity."
        )

    top = sorted(uploaded, key=lambda v: _safe_num(v.get("performance_score")), reverse=True)[:5]
    weak = sorted(uploaded, key=lambda v: _safe_num(v.get("performance_score")))[:5]

    def line(video: dict) -> str:
        m = video.get("metrics", {})
        return (
            f"{video.get('content_format', 'unknown')} | {video.get('category', 'unknown')} | "
            f"hook: {video.get('hook', '')[:80]} | "
            f"views {int(_safe_num(m.get('views')))}, "
            f"avg% {round(_safe_num(m.get('averageViewPercentage')), 1)}, "
            f"likes {int(_safe_num(m.get('likes')))}, "
            f"shares {int(_safe_num(m.get('shares')))}, "
            f"subs+ {int(_safe_num(m.get('subscribersGained')))}"
        )

    return "\n".join([
        f"Analytics sample: {len(uploaded)} uploaded videos. Treat as directional, not absolute.",
        "Top performers:",
        *[f"- {line(v)}" for v in top],
        "Weak performers:",
        *[f"- {line(v)}" for v in weak],
        "Instruction: echo winning patterns in specificity, hook shape, format, and emotional trigger. Do not repeat exact topics or hooks.",
    ])
