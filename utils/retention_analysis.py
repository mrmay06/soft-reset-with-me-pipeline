"""Pure audience-retention curve analysis for the weekly strategy job.

YouTube's curve is audienceWatchRatio sampled on elapsedVideoTimeRatio (0..1).
For Shorts the ratio routinely exceeds 1.0 because of loops and rewatches, so
every loss here is measured relative to the curve's own opening level, never
against an assumed 1.0 start.
"""
from __future__ import annotations

DEFAULT_HOOK_WINDOW_SEC = 3.0
DEFAULT_CLIFF_WINDOW_SEC = 1.0
DEFAULT_MIN_CLIFF_PCT = 3.0
DEFAULT_MAX_CLIFFS = 3
DEFAULT_NOISY_VIEWS = 1000
OPENING_WINDOW_SEC = 1.0
ENDING_SHARE = 0.9
AFTER_VOICE_LABEL = "[after voiceover: ending tail]"


def parse_curve_rows(response: dict) -> list[list[float]]:
    """[[ratio, audienceWatchRatio, relativeRetentionPerformance|None], ...] sorted by ratio."""
    headers = [h.get("name") for h in (response or {}).get("columnHeaders", [])]
    try:
        i_ratio = headers.index("elapsedVideoTimeRatio")
        i_watch = headers.index("audienceWatchRatio")
    except ValueError:
        return []
    i_rel = headers.index("relativeRetentionPerformance") if "relativeRetentionPerformance" in headers else None
    points = []
    for row in (response or {}).get("rows", []) or []:
        try:
            ratio, watch = float(row[i_ratio]), float(row[i_watch])
        except (TypeError, ValueError, IndexError):
            continue
        rel = None
        if i_rel is not None:
            try:
                rel = round(float(row[i_rel]), 4)
            except (TypeError, ValueError, IndexError):
                rel = None
        points.append([round(ratio, 4), round(watch, 4), rel])
    return sorted(points, key=lambda p: p[0])


def _value_at(series: list[tuple[float, float]], t: float) -> float:
    """Linear interpolation on (seconds, watch) pairs, clamped to the ends."""
    if t <= series[0][0]:
        return series[0][1]
    for (t0, v0), (t1, v1) in zip(series, series[1:]):
        if t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return series[-1][1]


def line_at(timeline: dict, second: float) -> dict | None:
    """The spoken line playing at `second`, or an ending-tail marker after the voice stops."""
    lines = (timeline or {}).get("lines") or []
    if not lines:
        return None
    voice_end = timeline.get("voice_end_sec")
    if voice_end is not None and second > float(voice_end):
        return {"section": "ending_tail", "text": AFTER_VOICE_LABEL}
    current = lines[0]
    for line in lines:
        if float(line.get("start", 0)) <= second:
            current = line
        else:
            break
    return {"section": current.get("section", ""), "text": current.get("text", "")}


def _pct_of(level: float, base: float) -> float:
    return round(level / base * 100, 1) if base > 0 else 0.0


def analyze_curve(
    points: list[list[float]],
    duration_sec: float,
    timeline: dict | None = None,
    views: int | None = None,
    hook_window_sec: float = DEFAULT_HOOK_WINDOW_SEC,
    cliff_window_sec: float = DEFAULT_CLIFF_WINDOW_SEC,
    min_cliff_pct: float = DEFAULT_MIN_CLIFF_PCT,
    max_cliffs: int = DEFAULT_MAX_CLIFFS,
    noisy_views: int = DEFAULT_NOISY_VIEWS,
) -> dict:
    """Hook leak, top cliffs, mid-video slide and end retention for one curve.

    All percentages are "% of the opening level" so curves inflated above 1.0 by
    loops stay comparable with curves that are not.
    """
    duration = float(duration_sec or 0)
    if duration <= 0 or len(points) < 3:
        return {"status": "insufficient_data", "reason": "missing duration" if duration <= 0 else "too few curve points"}

    series = [(float(p[0]) * duration, float(p[1])) for p in points]
    opening = max(v for t, v in series if t <= series[0][0] + OPENING_WINDOW_SEC)
    if opening <= 0:
        return {"status": "insufficient_data", "reason": "empty curve"}

    hook_end = min(hook_window_sec, duration)
    at_hook = _value_at(series, hook_end)
    hook_leak = max(0.0, _pct_of(opening - at_hook, opening))

    # Cliffs: the steepest loss inside any short window after the hook, so one
    # noisy sample cannot masquerade as a cliff and the hook is not double counted.
    candidates = []
    for t, v in series:
        if t < hook_end or t + cliff_window_sec > duration:
            continue
        drop = _pct_of(v - _value_at(series, t + cliff_window_sec), opening)
        if drop >= min_cliff_pct:
            candidates.append((drop, t))
    cliffs = []
    for drop, t in sorted(candidates, reverse=True):
        if any(abs(t - c["start_sec"]) < cliff_window_sec for c in cliffs):
            continue
        at = round(t + cliff_window_sec / 2, 1)
        cliff = {"start_sec": round(t, 1), "at_sec": at, "drop_pct": drop}
        spoken = line_at(timeline or {}, at)
        if spoken:
            cliff["section"] = spoken["section"]
            cliff["line"] = spoken["text"]
        cliffs.append(cliff)
        if len(cliffs) >= max_cliffs:
            break
    cliffs.sort(key=lambda c: c["start_sec"])

    mid_end = max(hook_end, duration * ENDING_SHARE)
    mid_span = mid_end - hook_end
    mid_slide = None
    if mid_span > 0:
        lost = _pct_of(at_hook - _value_at(series, mid_end), opening)
        mid_slide = round(lost / mid_span * 10, 1)

    end_value = series[-1][1]
    rel_values = [p[2] for p in points if len(p) > 2 and p[2] is not None]
    result = {
        "status": "ok",
        "confidence": "low" if views is not None and views < noisy_views else "normal",
        "duration_sec": round(duration, 1),
        "opening_watch_ratio": round(opening, 3),
        "loop_inflated": max(v for _, v in series) > 1.0,
        "hook_window_sec": hook_end,
        "hook_leak_pct": hook_leak,
        "hook_retained_pct": _pct_of(at_hook, opening),
        "cliffs": cliffs,
        "mid_slide_pct_per_10s": mid_slide,
        "end_watch_ratio": round(end_value, 3),
        "end_retention_pct_of_opening": _pct_of(end_value, opening),
        "avg_relative_retention": round(sum(rel_values) / len(rel_values), 3) if rel_values else None,
    }
    if timeline:
        hook_line = line_at(timeline, min(hook_end, float(timeline.get("voice_end_sec") or hook_end)))
        if hook_line:
            result["line_at_hook_end"] = hook_line["text"]
        result["timeline_source"] = timeline.get("source", "")
    return result


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def aggregate_patterns(analyses: list[dict]) -> dict:
    """Channel-level retention patterns across the per-video analyses that succeeded."""
    ok = [a for a in analyses if a.get("status") == "ok"]
    if not ok:
        return {"videos_with_curves": 0}
    reliable = [a for a in ok if a.get("confidence") != "low"]
    cliffs = [c for a in ok for c in a.get("cliffs", [])]
    by_section: dict[str, int] = {}
    for cliff in cliffs:
        section = cliff.get("section") or "unmapped"
        by_section[section] = by_section.get(section, 0) + 1
    leaks = sorted(a["hook_leak_pct"] for a in ok)
    return {
        "videos_with_curves": len(ok),
        "videos_normal_confidence": len(reliable),
        "avg_hook_leak_pct": _mean(leaks),
        "median_hook_leak_pct": leaks[len(leaks) // 2],
        "avg_hook_leak_pct_normal_confidence": _mean([a["hook_leak_pct"] for a in reliable]),
        "avg_mid_slide_pct_per_10s": _mean([a.get("mid_slide_pct_per_10s") for a in ok]),
        "avg_end_retention_pct_of_opening": _mean([a.get("end_retention_pct_of_opening") for a in ok]),
        "loop_inflated_videos": sum(1 for a in ok if a.get("loop_inflated")),
        "cliff_count_by_section": dict(sorted(by_section.items(), key=lambda kv: -kv[1])),
        "avg_cliff_position_pct_of_video": _mean([
            c["at_sec"] / a["duration_sec"] * 100 for a in ok for c in a.get("cliffs", []) if a.get("duration_sec")
        ]),
    }
