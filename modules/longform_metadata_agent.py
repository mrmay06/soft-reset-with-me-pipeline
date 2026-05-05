from __future__ import annotations

import os
import re

from utils.gemini_client import generate_json
from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry
from utils.youtube_tags import sanitize_youtube_tags


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _generate_packaging(prompt: str, model: str) -> dict:
    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Long-form packaging returned non-object JSON")
    return result


def _safe_title(text: str, max_chars: int) -> str:
    title = re.sub(r"\s+", " ", str(text or "Soft Reset With Me")).strip()
    title = title.replace("—", " ").replace("–", " ").replace("--", " ")
    if len(title) <= max_chars:
        return title.rstrip(".:-'\" ").strip()
    clipped = title[:max_chars].rsplit(" ", 1)[0]
    return (clipped or title[:max_chars]).rstrip(".:-'\" ").strip()


def _clean_thumb_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace("—", " ").replace("–", " ").replace("--", " ")
    text = re.sub(r"[^\w\s']", "", text)
    words = text.upper().split()
    return " ".join(words[:5]).strip()


def _fallback_variants(research: dict, max_title_chars: int) -> dict:
    working_title = _safe_title(research.get("working_title", "Soft Reset With Me"), max_title_chars)
    topic = str(research.get("topic", "")).strip()
    topic_lower = topic.lower()
    core_claim = str(research.get("core_claim", "")).strip()
    viewer_pain = str(research.get("viewer_pain", "")).strip()
    retention_hook = str(research.get("retention_hook", "")).strip()
    pillar = str(research.get("content_pillar", "")).lower()

    if "ghost" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "Why Ghosting Hurts Even When It Wasn't Serious"),
            ("B", "emotional", "specific scenario", "The Silence After The Spark Hurts For A Reason"),
            ("C", "counter", "counter-intuitive", "You're Not Missing Them. You're Missing Closure"),
        ]
        thumbs = [
            ("A", "seo", "clean_concept_close_up", "GHOSTING HITS HARD"),
            ("B", "emotional", "digital_anxiety_overlay", "LEFT ON READ"),
            ("C", "counter", "subject_vs_the_void", "IT WASN'T NOTHING"),
        ]
    elif "potential" in topic_lower or "imagined" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "Why You Miss Their Potential More Than Them"),
            ("B", "emotional", "curiosity gap", "You're Grieving A Future That Never Happened"),
            ("C", "counter", "counter-intuitive", "You Didn't Miss Them. You Missed The Dream"),
        ]
        thumbs = [
            ("A", "seo", "clean_concept_close_up", "YOU MISS THE DREAM"),
            ("B", "emotional", "digital_anxiety_overlay", "IT FELT REAL"),
            ("C", "counter", "dichotomy_split", "NOT THE PERSON"),
        ]
    elif "strong one" in topic_lower or "strong" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "When Being The Strong One Starts To Break You"),
            ("B", "emotional", "specific scenario", "No One Notices When The Strong One Is Drowning"),
            ("C", "counter", "counter-intuitive", "Strength Can Be A Form Of Self-Abandonment"),
        ]
        thumbs = [
            ("A", "seo", "clean_concept_close_up", "TIRED OF CARRYING"),
            ("B", "emotional", "clean_concept_close_up", "NO ONE ASKED"),
            ("C", "counter", "subject_vs_the_void", "STRENGTH IS HIDING"),
        ]
    else:
        titles = [
            ("A", "seo", "specific scenario", working_title),
            ("B", "emotional", "curiosity gap", _safe_title(retention_hook or f"Why {topic} Still Hurts More Than It Should", max_title_chars)),
            ("C", "counter", "counter-intuitive", _safe_title(core_claim or "It's Not About Them. It's About The Pattern", max_title_chars)),
        ]
        thumbs = [
            ("A", "seo", "clean_concept_close_up", _clean_thumb_text(topic) or "THE REAL REASON"),
            ("B", "emotional", "digital_anxiety_overlay", "THIS PART HURTS"),
            ("C", "counter", "dichotomy_split", "YOU ALREADY KNEW"),
        ]

    pillar_tags = {
        "relationship patterns": [
            "relationship advice", "dating advice", "attachment style", "situationship",
            "red flags in relationships", "love bombing", "emotional unavailability",
            "anxious attachment", "avoidant attachment", "trauma bonding",
        ],
        "psychology drops": [
            "relationship advice", "emotional health", "self awareness", "attachment style",
            "psychology of relationships", "nervous system healing", "emotional intelligence",
            "self awareness tips", "mental health relationships", "emotional regulation",
        ],
        "healing arcs": [
            "relationship advice", "breakup advice", "healing journey", "moving on",
            "how to get over someone you love", "breakup recovery", "emotional healing",
            "self healing after breakup", "signs you re not over your ex", "moving on after breakup",
        ],
        "self-worth shifts": [
            "relationship advice", "self worth", "self respect", "personal growth",
            "know your worth", "setting boundaries in relationships", "self love",
            "standards in relationships", "stop settling", "emotional boundaries",
        ],
        "conversation truths": [
            "relationship advice", "communication skills", "dating advice", "self awareness",
            "healthy communication in relationships", "conflict resolution", "emotional honesty",
            "what to say in relationships", "hard conversations", "relationship communication tips",
        ],
        "identity and growth": [
            "relationship advice", "personal growth", "self worth", "emotional healing",
            "self improvement", "emotional maturity", "growth mindset relationships",
            "reinventing yourself", "self discovery", "becoming a better person",
        ],
    }
    base_tags = pillar_tags.get(pillar, ["relationship advice", "emotional healing", "personal growth",
                                          "self worth", "healing journey", "dating advice",
                                          "attachment style", "moving on", "personal growth tips"])
    tags = ["soft reset with me", *base_tags, "softreset"]

    only_soft_reset_line = str(research.get("only_soft_reset_line", "")).strip()
    comment_driver = (
        f"{only_soft_reset_line} Has this ever happened to you? Drop it in the comments."
        if only_soft_reset_line
        else "Has this ever happened to you? Drop your experience in the comments."
    )
    description = (
        f"{core_claim}\n\n"
        f"A quiet Soft Reset for anyone who recognizes this: {viewer_pain or topic}\n\n"
        f"{comment_driver}\n\n"
        "Subscribe for softer resets — @SoftResetWithMe\n\n"
        "#SoftResetWithMe #RelationshipAdvice #EmotionalHealing #PersonalGrowth #HealingJourney"
    )
    return {
        "primary_variant_id": "B",
        "description": description,
        "tags": tags,
        "title_variants": [
            {"id": item[0], "angle": item[1], "formula": item[2], "title": _safe_title(item[3], max_title_chars)}
            for item in titles
        ],
        "thumbnail_variants": [
            {"id": item[0], "angle": item[1], "pattern": item[2], "thumbnail_text": _clean_thumb_text(item[3])}
            for item in thumbs
        ],
    }


def _validate_packaging(raw: dict, research: dict, max_title_chars: int) -> dict:
    fallback = _fallback_variants(research, max_title_chars)
    title_variants = raw.get("title_variants", []) if isinstance(raw.get("title_variants"), list) else []
    thumb_variants = raw.get("thumbnail_variants", []) if isinstance(raw.get("thumbnail_variants"), list) else []

    title_by_id = {}
    for item in title_variants:
        vid = str(item.get("id", "")).upper()
        title = _safe_title(item.get("title", ""), max_title_chars)
        if vid in {"A", "B", "C"} and title:
            title_by_id[vid] = {
                "id": vid,
                "angle": str(item.get("angle", "")).lower() or {"A": "seo", "B": "emotional", "C": "counter"}[vid],
                "formula": str(item.get("formula", "")).strip() or "",
                "title": title,
            }
    for item in fallback["title_variants"]:
        title_by_id.setdefault(item["id"], item)

    thumb_by_id = {}
    for item in thumb_variants:
        vid = str(item.get("id", "")).upper()
        text = _clean_thumb_text(item.get("thumbnail_text", ""))
        if vid in {"A", "B", "C"} and text:
            entry = {
                "id": vid,
                "angle": str(item.get("angle", "")).lower() or {"A": "seo", "B": "emotional_hook", "C": "counter_intuitive"}[vid],
                "pattern": str(item.get("pattern", "")).strip() or fallback["thumbnail_variants"][ord(vid) - 65]["pattern"],
                "thumbnail_text": text,
            }
            # Preserve AI-generated visual prompt if present; thumbnail agent will build its own PIL text layer
            ai_prompt = str(item.get("prompt", "")).strip()
            if ai_prompt:
                entry["visual_prompt"] = ai_prompt
            thumb_by_id[vid] = entry
    for item in fallback["thumbnail_variants"]:
        fb_entry = {k: v for k, v in item.items() if k != "prompt"}
        thumb_by_id.setdefault(item["id"], fb_entry)

    primary_variant_id = str(raw.get("primary_variant_id", fallback["primary_variant_id"])).upper()
    if primary_variant_id not in {"A", "B", "C"}:
        primary_variant_id = fallback["primary_variant_id"]

    return {
        "primary_variant_id": primary_variant_id,
        "description": str(raw.get("description", fallback["description"])).strip() or fallback["description"],
        "tags": raw.get("tags", fallback["tags"]),
        "title_variants": [title_by_id[key] for key in ("A", "B", "C")],
        "thumbnail_variants": [thumb_by_id[key] for key in ("A", "B", "C")],
    }


def run_longform_metadata(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_metadata] Building A/B packaging for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    hook = script.get("chapters", [{}])[0].get("voiceover", "") if script.get("chapters") else ""
    max_title_chars = int(config.get("max_title_chars", 70))
    template = open("prompts/longform_packaging_prompt.txt").read()
    prompt = template.format(
        max_title_chars=max_title_chars,
        topic=research.get("topic", ""),
        working_title=research.get("working_title", ""),
        content_pillar=research.get("content_pillar", ""),
        core_claim=research.get("core_claim", ""),
        viewer_pain=research.get("viewer_pain", ""),
        retention_hook=research.get("retention_hook", ""),
        only_soft_reset_line=research.get("only_soft_reset_line", ""),
        hook=hook,
    )
    try:
        raw = _generate_packaging(prompt, config["metadata_model"])
    except Exception as exc:
        print(f"[longform_metadata] Packaging generation failed ({exc}); using fallback variants")
        raw = _fallback_variants(research, max_title_chars)

    packaged = _validate_packaging(raw, research, max_title_chars)
    description = packaged["description"]
    if "@softresetwithme" not in description.lower():
        description += "\n\nSubscribe for softer resets — @SoftResetWithMe"
    tags = sanitize_youtube_tags(
        packaged["tags"],
        config.get("youtube_tags_total_chars", 450),
        config.get("youtube_tags_max_count", 15),
    )
    primary_id = packaged["primary_variant_id"]
    primary_title = next(item["title"] for item in packaged["title_variants"] if item["id"] == primary_id)
    primary_thumb_text = next(item["thumbnail_text"] for item in packaged["thumbnail_variants"] if item["id"] == primary_id)

    result = {
        "video_id": video_id,
        "title": primary_title,
        "description": description,
        "tags": tags,
        "thumbnail_text": primary_thumb_text,
        "primary_variant_id": primary_id,
        "title_variants": packaged["title_variants"],
        "thumbnail_variants": packaged["thumbnail_variants"],
        "ab_test_ready": True,
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "metadata_strategy": "longform_ab_packaging_v2",
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "03_longform_metadata.json"))
    print(f"[longform_metadata] Done. Primary title [{primary_id}]: {primary_title}")
    return result


def run_longform_metadata_mock(video_id: str, run_dir: str, config: dict) -> dict:
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    packaged = _fallback_variants(research, int(config.get("max_title_chars", 70)))
    primary_id = packaged["primary_variant_id"]
    result = {
        "video_id": video_id,
        "title": next(item["title"] for item in packaged["title_variants"] if item["id"] == primary_id),
        "description": packaged["description"],
        "tags": packaged["tags"],
        "thumbnail_text": next(item["thumbnail_text"] for item in packaged["thumbnail_variants"] if item["id"] == primary_id),
        "primary_variant_id": primary_id,
        "title_variants": packaged["title_variants"],
        "thumbnail_variants": packaged["thumbnail_variants"],
        "ab_test_ready": True,
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "metadata_strategy": "longform_ab_packaging_v2_mock",
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "03_longform_metadata.json"))
    print(f"[longform_metadata][MOCK] Done.")
    return result
