from __future__ import annotations

import os

from utils.gemini_client import generate_json
from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry
from utils.youtube_tags import sanitize_youtube_tags


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _generate_metadata(prompt: str, model: str) -> dict:
    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Long-form metadata returned non-object JSON")
    return result


def _fallback(script: dict, research: dict) -> dict:
    title = research.get("working_title", "Soft Reset With Me")[:70].rstrip()
    topic = research.get("topic", "")
    core_claim = research.get("core_claim", "")
    viewer_pain = research.get("viewer_pain", "")
    pillar = str(research.get("content_pillar", "")).lower()
    pillar_tags = {
        "relationship patterns": ["relationship advice", "dating advice", "attachment style", "situationship"],
        "psychology drops": ["relationship advice", "emotional health", "self awareness", "attachment style"],
        "healing arcs": ["relationship advice", "breakup advice", "healing journey", "moving on"],
        "self-worth shifts": ["relationship advice", "self worth", "self respect", "personal growth"],
        "conversation truths": ["relationship advice", "communication skills", "dating advice", "self awareness"],
        "identity and growth": ["relationship advice", "personal growth", "self worth", "emotional healing"],
    }
    tags = ["soft reset with me", *pillar_tags.get(pillar, ["relationship advice", "emotional healing", "personal growth"])]
    topic = str(research.get("topic", "")).lower()
    if "potential" in topic or "imagined" in topic:
        thumbnail_text = "YOU MISS THE DREAM"
    elif "peace" in topic or "chaos" in topic:
        thumbnail_text = "WHY CALM FEELS WRONG"
    elif "strong one" in topic:
        thumbnail_text = "TIRED OF BEING STRONG"
    else:
        thumbnail_words = [word.strip(".,!?;:()[]\"'") for word in title.upper().split()]
        thumbnail_text = " ".join(thumbnail_words[:4]) or "SOFT RESET"
    return {
        "title": title,
        "description": (
            f"{core_claim}\n\n"
            f"A quiet Soft Reset for anyone who recognizes this: {viewer_pain or topic}.\n\n"
            "Subscribe for softer resets — @SoftResetWithMe\n\n"
            "#SoftResetWithMe #RelationshipAdvice #EmotionalHealing #PersonalGrowth"
        ),
        "tags": [*tags, "softreset"],
        "thumbnail_text": thumbnail_text,
    }


def run_longform_metadata(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_metadata] Generating metadata for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    hook = ""
    if script.get("chapters"):
        hook = script["chapters"][0].get("voiceover", "")
    template = open("prompts/longform_metadata_prompt.txt").read()
    prompt = template.format(
        max_title_chars=config.get("max_title_chars", 70),
        topic=research.get("topic", ""),
        working_title=research.get("working_title", ""),
        core_claim=research.get("core_claim", ""),
        viewer_pain=research.get("viewer_pain", ""),
        hook=hook,
    )
    try:
        raw = _generate_metadata(prompt, config["metadata_model"])
    except Exception as exc:
        print(f"[longform_metadata] Generation failed ({exc}); using fallback")
        raw = _fallback(script, research)

    title = str(raw.get("title", "")).replace("#Shorts", "").rstrip(".").strip()
    max_title = int(config.get("max_title_chars", 70))
    if len(title) > max_title:
        title = title[:max_title].rstrip()
    description = str(raw.get("description", "")).strip()
    if "@softresetwithme" not in description.lower():
        description += "\n\nSubscribe for softer resets — @SoftResetWithMe"
    tags = sanitize_youtube_tags(
        raw.get("tags", []),
        config.get("youtube_tags_total_chars", 450),
        config.get("youtube_tags_max_count", 15),
    )
    result = {
        "video_id": video_id,
        "title": title,
        "description": description,
        "tags": tags,
        "thumbnail_text": raw.get("thumbnail_text", ""),
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "03_longform_metadata.json"))
    print(f"[longform_metadata] Done. Title: {title}")
    return result


def run_longform_metadata_mock(video_id: str, run_dir: str, config: dict) -> dict:
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    result = {
        "video_id": video_id,
        **_fallback(script, research),
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "03_longform_metadata.json"))
    print(f"[longform_metadata][MOCK] Done.")
    return result
