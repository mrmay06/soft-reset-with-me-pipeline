from __future__ import annotations

import os

from utils.gemini_client import generate_json
from utils.helpers import load_json, save_json, now_iso
from utils.performance_insights import summarize_performance_for_prompt
from utils.retry import retry


def _recent_topics(memory_file: str) -> str:
    if not os.path.exists(memory_file):
        return "- None"
    data = load_json(memory_file)
    if not isinstance(data, list) or not data:
        return "- None"
    return "\n".join(f"- {item.get('topic', '')}" for item in data[-12:] if item.get("topic")) or "- None"


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _generate_longform_topic(prompt: str, model: str) -> dict:
    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Long-form research returned non-object JSON")
    return result


def run_longform_research(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_research] Selecting topic for {video_id}")
    template = open("prompts/longform_research_prompt.txt").read()
    performance_insights = summarize_performance_for_prompt(
        config.get("performance_memory_file", "performance_memory_soft_reset_long.json"),
        min_videos=int(config.get("performance_min_videos_for_prompt", 4)),
        pattern_min_videos=int(config.get("performance_pattern_min_videos", 12)),
        min_views=int(config.get("performance_min_views", 100)),
    )
    prompt = template.format(
        target_audience=config.get("target_audience", ""),
        niche=config.get("niche", ""),
        recent_topics=_recent_topics(config.get("topic_memory_file", "topic_memory_soft_reset_long.json")),
        performance_insights=performance_insights,
    )
    result = _generate_longform_topic(prompt, config["research_model"])
    result["video_id"] = video_id
    result["generated_at"] = now_iso()
    save_json(result, os.path.join(run_dir, "01_longform_research.json"))
    print(f"[longform_research] Done. Topic: {result.get('topic', '')}")
    return result


def run_longform_research_mock(video_id: str, run_dir: str, config: dict) -> dict:
    result = {
        "video_id": video_id,
        "topic": "Why you miss their potential more than the person",
        "working_title": "Why You Miss Their Potential More Than Them",
        "content_pillar": "healing arcs",
        "longform_format": "one_truth_expanded",
        "core_claim": "Some heartbreak lasts because you are grieving an imagined future, not the relationship you actually had.",
        "editorial_seed": "Missing someone is not always proof they were right for you. Sometimes it proves how much emotional future you rehearsed with them. The pain can be real even when the person was inconsistent.",
        "only_soft_reset_line": "You are allowed to grieve the version they never became.",
        "viewer_pain": "missing someone who gave almost enough to keep you hoping",
        "psych_concept": "idealization, rumination, and ambiguous loss",
        "retention_hook": "If you keep missing someone who barely showed up, this might be why.",
        "chapter_arc": [
            {"chapter": "hook", "purpose": "name the contradiction", "duration_sec": 25},
            {"chapter": "name the pain", "purpose": "separate person from potential", "duration_sec": 60},
            {"chapter": "hidden pattern", "purpose": "explain rehearsed futures", "duration_sec": 100},
            {"chapter": "reframe", "purpose": "release the fantasy without shaming the grief", "duration_sec": 130},
            {"chapter": "soft reset", "purpose": "close with a grounded next step", "duration_sec": 80}
        ],
        "visual_mood": "rainy windows, quiet rooms, empty chairs, journals, city night walks",
        "why_now": "Situationship grief is common in dating app culture where almost-relationships can feel emotionally complete.",
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "01_longform_research.json"))
    print(f"[longform_research][MOCK] Done. Topic: {result['topic']}")
    return result
