"""
Creative Judge — pre-publish gate plus learning signal.
Scores 13 creative dimensions, extracts trait labels, writes 10_judge_report.json,
and blocks upload on hard quality/safety failures.
"""
from __future__ import annotations

import os

from utils.helpers import load_json, save_json, now_iso
from utils.gemini_client import generate_json
from utils.retry import retry
from utils.strategy import get_strategy_version

JUDGE_DIMENSIONS = [
    "hook_strength",
    "script_clarity",
    "editorial_pov",
    "villain_mechanism_specificity",
    "cta_quality",
    "title_accuracy",
    "description_usefulness",
    "visual_dialogue_sync",
    "image_direction_strength",
    "thumbnail_concept",
    "voice_pacing_readiness",
    "brand_consistency",
    "policy_factual_risk",
]


def _extract_hook_type(hook: str) -> str:
    h = hook.lower().strip()
    if h.endswith("?"):
        return "question"
    for prefix in ("you're", "you are", "stop ", "they ", "this is ", "it's not", "when they"):
        if h.startswith(prefix):
            return "direct_accusation"
    for phrase in ("what if", "nobody tells", "the real reason", "here's why", "turns out", "the truth"):
        if phrase in h:
            return "counter_intuitive"
    return "statement"


def _extract_title_type(title: str) -> str:
    t = title.lower().strip()
    if t.endswith("?"):
        return "question"
    for prefix in ("your ", "you ", "they ", "stop ", "this ", "when ", "why "):
        if t.startswith(prefix):
            return "accusation"
    if len(title.split()) <= 5:
        return "fragment"
    return "declarative"


def _visual_style_mix(scenes: list[dict]) -> str:
    if not scenes:
        return "unknown"
    brand = sum(
        1
        for s in scenes
        if s.get("visual_type", s.get("type")) == "image"
        and s.get("image_style", s.get("style")) == "brand"
    )
    stock = sum(1 for s in scenes if s.get("visual_type", s.get("type")) == "video")
    total = len(scenes)
    if brand / total >= 0.4:
        return "brand_heavy"
    if stock / total >= 0.7:
        return "stock_heavy"
    return "balanced"


def _length_band(seconds: float) -> str:
    if seconds <= 0:
        return "unknown"
    if seconds < 30:
        return "under_30s"
    if seconds < 45:
        return "30_45s"
    if seconds < 60:
        return "45_60s"
    if seconds < 180:
        return "60s_3min"
    if seconds < 420:
        return "3_7min"
    return "over_7min"


def _load(run_dir: str, *paths: str) -> dict:
    for p in paths:
        full = os.path.join(run_dir, p)
        if os.path.exists(full):
            return load_json(full)
    return {}


def _score_value(scores: dict, name: str) -> int:
    item = scores.get(name, {})
    if isinstance(item, dict):
        try:
            return int(item.get("score", 0))
        except (TypeError, ValueError):
            return 0
    try:
        return int(item)
    except (TypeError, ValueError):
        return 0


def _hard_failures(raw: dict, script: dict, config: dict) -> list[str]:
    scores = raw.get("scores", {}) if isinstance(raw.get("scores", {}), dict) else {}
    failures = []

    is_longform = config.get("longform_target_words_min") is not None
    if is_longform:
        min_w = int(config.get("longform_target_words_min", 750))
        max_w = int(config.get("longform_target_words_max", 1050))
        hard_min_w = int(config.get("longform_hard_words_min", max(1, min_w - 100)))
        hard_max_w = int(config.get("longform_hard_words_max", max_w + 150))
    else:
        min_w = int(config.get("script_min_words", 45))
        max_w = int(config.get("script_max_words", 75))
        hard_min_w = int(config.get("script_hard_min_words", max(1, min_w - 10)))
        hard_max_w = int(config.get("script_hard_max_words", max_w + 20))
    words = script.get("word_count", 0)
    if isinstance(words, int) and not (hard_min_w <= words <= hard_max_w):
        failures.append("word_count_hard_limit")

    if script.get("validation") in {"forced", "needs_review"} or script.get("human_review_required"):
        failures.append("script_validation_passed")

    composite_min = float(config.get("creative_judge_min_composite", 5.5))
    policy_min = int(config.get("creative_judge_min_policy_risk", 7))
    clarity_min = int(config.get("creative_judge_min_script_clarity", 6))
    title_min = int(config.get("creative_judge_min_title_accuracy", 6))

    try:
        composite = float(raw.get("composite_score", 0))
    except (TypeError, ValueError):
        composite = 0.0

    if composite < composite_min:
        failures.append("creative_composite")
    if _score_value(scores, "policy_factual_risk") < policy_min:
        failures.append("policy_factual_risk")
    if _score_value(scores, "script_clarity") < clarity_min:
        failures.append("script_clarity")
    if _score_value(scores, "title_accuracy") < title_min:
        failures.append("title_accuracy")

    return failures


def _soft_warnings(script: dict, config: dict) -> list[str]:
    warnings = []
    is_longform = config.get("longform_target_words_min") is not None
    if is_longform:
        min_w = int(config.get("longform_target_words_min", 750))
        max_w = int(config.get("longform_target_words_max", 1050))
    else:
        min_w = int(config.get("script_min_words", 45))
        max_w = int(config.get("script_max_words", 75))
    words = script.get("word_count", 0)
    if isinstance(words, int) and not (min_w <= words <= max_w):
        warnings.append("word_count_in_range")
    return warnings


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _call_judge(prompt: str, model: str) -> dict:
    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Judge returned non-object JSON")
    return result


def run_creative_judge(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[creative_judge] Scoring {video_id}")

    research = _load(run_dir, "01_research.json", "01_longform_research.json")
    script = _load(run_dir, "02_script.json", "02_longform_script.json")
    metadata = _load(run_dir, "07_metadata.json", "03_longform_metadata.json")
    render_meta = _load(run_dir, "06_render_meta.json", "06_longform_render_meta.json")
    upload_meta = _load(run_dir, "08_upload_meta.json", "09_longform_upload_meta.json")
    scene_manifest = _load(run_dir, "03b_scene_manifest.json")

    scenes = scene_manifest.get("scenes", [])
    brand_image_count = sum(
        1
        for s in scenes
        if s.get("visual_type", s.get("type")) == "image"
        and s.get("image_style", s.get("style")) == "brand"
    )
    stock_video_count = sum(1 for s in scenes if s.get("visual_type", s.get("type")) == "video")

    hook = script.get("hook", "")
    title = metadata.get("title", "")
    description = metadata.get("description", "")
    duration = render_meta.get("duration_seconds", render_meta.get("duration_sec", render_meta.get("final_duration_sec", 0)))

    prompt = f"""You are a creative quality judge for Soft Reset With Me, a faceless YouTube relationship/self-growth channel.
Score this video on each dimension from 1–10. Be precise and direct.
This is a pre-publish gate. Be strict about clarity, accuracy, title honesty, and policy risk.

VIDEO DETAILS:
Hook: {hook}
Title: {title}
Description (first 150 chars): {description[:150]}
Script word count: {script.get("word_count", "unknown")}
Category: {research.get("category", "unknown")}
Angle type: {research.get("angle_type", research.get("angle", "unknown"))}
Total scenes: {len(scenes)}  |  Brand images: {brand_image_count}  |  Stock videos: {stock_video_count}
Video duration: {round(duration)}s

SCORING RULES:
- policy_factual_risk: score 1 = serious risk, 10 = no risk (inverted scale)
- only_soft_reset_score: how uniquely could only this channel say this? 1 = anyone could say this, 10 = unmistakably ours

Return ONLY valid JSON:
{{
  "scores": {{
    "hook_strength": {{"score": 0, "reason": ""}},
    "script_clarity": {{"score": 0, "reason": ""}},
    "editorial_pov": {{"score": 0, "reason": ""}},
    "villain_mechanism_specificity": {{"score": 0, "reason": ""}},
    "cta_quality": {{"score": 0, "reason": ""}},
    "title_accuracy": {{"score": 0, "reason": ""}},
    "description_usefulness": {{"score": 0, "reason": ""}},
    "visual_dialogue_sync": {{"score": 0, "reason": ""}},
    "image_direction_strength": {{"score": 0, "reason": ""}},
    "thumbnail_concept": {{"score": 0, "reason": ""}},
    "voice_pacing_readiness": {{"score": 0, "reason": ""}},
    "brand_consistency": {{"score": 0, "reason": ""}},
    "policy_factual_risk": {{"score": 0, "reason": ""}}
  }},
  "composite_score": 0,
  "strongest_element": "",
  "weakest_element": "",
  "only_soft_reset_score": 0,
  "only_soft_reset_reason": ""
}}"""

    model = config.get("creative_judge_model", config.get("metadata_model", "gemini-2.0-flash"))
    try:
        raw = _call_judge(prompt, model)
    except Exception as e:
        print(f"[creative_judge] Gemini failed ({e}) — using null scores")
        raw = {
            "scores": {dim: {"score": 0, "reason": "judge_unavailable"} for dim in JUDGE_DIMENSIONS},
            "composite_score": 0,
            "strongest_element": "",
            "weakest_element": "",
            "only_soft_reset_score": 0,
            "only_soft_reset_reason": "judge_unavailable",
        }

    hard_failures = _hard_failures(raw, script, config)
    soft_warnings = _soft_warnings(script, config)
    passed = not hard_failures

    result = {
        "video_id": video_id,
        "youtube_video_id": upload_meta.get("youtube_video_id", ""),
        "youtube_url": upload_meta.get("youtube_url", ""),
        "track": "longform" if video_id.startswith("long_") else "shorts",
        "strategy_version": config.get("strategy_version", get_strategy_version()),
        "experiment_label": config.get("experiment_label", "baseline"),
        "experiment_id": config.get("experiment_id"),
        "traits": {
            "hook_type": _extract_hook_type(hook),
            "title_type": _extract_title_type(title),
            "angle_type": research.get("angle_type", research.get("angle", "unknown")),
            "category": research.get("category", "unknown"),
            "topic_cluster": research.get("topic", "")[:60],
            "visual_style_mix": _visual_style_mix(scenes),
            "video_length_band": _length_band(duration),
            "narrative_format": script.get("narrative_format", "unknown"),
            "thumbnail_type": metadata.get("thumbnail_type", "text_only"),
            "character_used": "brand_still" if brand_image_count > 0 else "none",
            "total_scenes": len(scenes),
        },
        "scores": raw.get("scores", {}),
        "composite_score": raw.get("composite_score", 0),
        "strongest_element": raw.get("strongest_element", ""),
        "weakest_element": raw.get("weakest_element", ""),
        "only_soft_reset_score": raw.get("only_soft_reset_score", 0),
        "only_soft_reset_reason": raw.get("only_soft_reset_reason", ""),
        "gate": "passed" if passed else "failed",
        "passed": passed,
        "hard_failures": hard_failures,
        "soft_warnings": soft_warnings,
        "judged_at": now_iso(),
    }

    save_json(result, os.path.join(run_dir, "10_judge_report.json"))
    if hard_failures:
        print(f"[creative_judge] GATE FAILED — hard failures: {hard_failures}")
    elif soft_warnings:
        print(f"[creative_judge] Gate passed with soft warnings: {soft_warnings}")
    else:
        print(
            f"[creative_judge] Gate passed. Composite: {result['composite_score']}/10  "
            f"| Strongest: {result['strongest_element']}  "
            f"| Weakest: {result['weakest_element']}"
        )
    return result


def run_creative_judge_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[creative_judge][MOCK] Skipping judge")
    result = {
        "video_id": video_id,
        "youtube_video_id": "MOCK",
        "track": "longform" if video_id.startswith("long_") else "shorts",
        "strategy_version": config.get("strategy_version", get_strategy_version()),
        "experiment_label": "baseline",
        "experiment_id": None,
        "traits": {
            "hook_type": "direct_accusation",
            "title_type": "accusation",
            "angle_type": "unknown",
            "category": "unknown",
            "topic_cluster": "mock",
            "visual_style_mix": "balanced",
            "video_length_band": "under_30s",
            "narrative_format": "unknown",
            "thumbnail_type": "text_only",
            "character_used": "brand_still",
            "total_scenes": 0,
        },
        "scores": {dim: {"score": 7, "reason": "mock"} for dim in JUDGE_DIMENSIONS},
        "composite_score": 7,
        "strongest_element": "mock",
        "weakest_element": "mock",
        "only_soft_reset_score": 7,
        "only_soft_reset_reason": "mock",
        "gate": "passed",
        "passed": True,
        "hard_failures": [],
        "mock": True,
        "judged_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "10_judge_report.json"))
    return result
