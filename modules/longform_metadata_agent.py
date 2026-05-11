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


def _clean_thumb_line1(text: str) -> str:
    text = _clean_thumb_text(text)
    words = text.split()
    return " ".join(words[:4]).strip()


def _clean_thumb_line2(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    text = text.replace("—", " ").replace("–", " ").replace("--", " ")
    text = re.sub(r"[^\w\s']", "", text)
    words = text.lower().split()
    return " ".join(words[:6]).strip()


def _combine_thumb_copy(line1: str, line2: str) -> str:
    return " / ".join(part for part in (_clean_thumb_line1(line1), _clean_thumb_line2(line2)) if part)


def _split_legacy_thumb_text(text: str) -> tuple[str, str]:
    line1 = _clean_thumb_line1(text)
    if line1:
        return line1, "this is why it hurts"
    return "YOU ALREADY KNOW", "this is why it hurts"


_CLINICAL_THUMB_WORDS = {
    "withdrawal", "reinforcement", "regulation", "dysregulation", "intermittent",
    "subconscious", "pattern", "attachment", "nervous", "system", "trauma",
    "process", "journey", "healing", "toxic", "growth", "explained",
}


def _thumb_text_is_clinical(text: str) -> bool:
    words = set(text.lower().split())
    return bool(words & _CLINICAL_THUMB_WORDS)


def _thumb_variant_is_clinical(item: dict) -> bool:
    return _thumb_text_is_clinical(
        " ".join(
            str(item.get(key, ""))
            for key in ("thumbnail_text", "line1", "line2", "thumb_line1", "thumb_line2")
        )
    )


def _pick_primary_variant(variants: list[dict], thumb_variants: list[dict]) -> str:
    """Pick B by default unless C is a genuine counter-intuitive and its thumb text is non-clinical.
    Never pick A as primary."""
    c_thumb = next((t for t in thumb_variants if t.get("id") == "C"), None)
    c_title = next((t for t in variants if t.get("id") == "C"), None)
    if c_thumb and c_title:
        if not _thumb_variant_is_clinical(c_thumb):
            return "C"
    return "B"


def _fallback_variants(research: dict, max_title_chars: int) -> dict:
    working_title = _safe_title(research.get("working_title", "Soft Reset With Me"), max_title_chars)
    topic = str(research.get("topic", "")).strip()
    topic_lower = topic.lower()
    core_claim = str(research.get("core_claim", "")).strip()
    viewer_pain = str(research.get("viewer_pain", "")).strip()
    retention_hook = str(research.get("retention_hook", "")).strip()
    only_soft_reset_line = str(research.get("only_soft_reset_line", "")).strip()
    pillar = str(research.get("content_pillar", "")).lower()

    if "ghost" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "Why Ghosting Hurts Even When It Wasn't Serious"),
            ("B", "emotional", "specific scenario", "The Silence After The Last Message Still Hits"),
            ("C", "counter", "counter-intuitive", "You're Not Missing Them. You're Missing Closure"),
        ]
        thumbs = [
            ("A", "seo", "one_face_right_negative_space_left", "IT WASN'T NOTHING", "here's why it hurts"),
            ("B", "emotional", "one_face_right_negative_space_left", "LEFT ON READ", "and still waiting"),
            ("C", "counter", "one_face_right_negative_space_left", "YOU MISS THE ENDING", "not just the person"),
        ]
    elif "potential" in topic_lower or "imagined" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "Why You Miss Their Potential More Than Them"),
            ("B", "emotional", "curiosity gap", "You're Grieving A Future That Never Happened"),
            ("C", "counter", "counter-intuitive", "You Didn't Miss Them. You Missed The Dream"),
        ]
        thumbs = [
            ("A", "seo", "one_face_right_negative_space_left", "YOU MISS THE DREAM", "not just the person"),
            ("B", "emotional", "one_face_right_negative_space_left", "IT FELT REAL", "even when it wasn't"),
            ("C", "counter", "one_face_right_negative_space_left", "NOT THE PERSON", "the future you imagined"),
        ]
    elif "strong one" in topic_lower or "strong" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "When Being The Strong One Finally Breaks You"),
            ("B", "emotional", "specific scenario", "No One Notices When The Strong One Is Drowning"),
            ("C", "counter", "counter-intuitive", "That's Not Strength. That's Loneliness With Good Posture"),
        ]
        thumbs = [
            ("A", "seo", "one_face_right_negative_space_left", "TIRED OF CARRYING", "everyone else's weight"),
            ("B", "emotional", "one_face_right_negative_space_left", "NO ONE ASKED", "if you were okay"),
            ("C", "counter", "one_face_right_negative_space_left", "THAT'S NOT STRENGTH", "it's loneliness with posture"),
        ]
    elif "peace" in topic_lower or "boring" in topic_lower or "calm" in topic_lower or "chaos" in topic_lower:
        titles = [
            ("A", "seo", "specific scenario", "Why Healthy Love Feels Boring After a Chaotic Relationship"),
            ("B", "emotional", "curiosity gap", "You Confuse Calm For Something Missing"),
            ("C", "counter", "counter-intuitive", "That Spark You Miss? It Was Just Anxiety"),
        ]
        thumbs = [
            ("A", "seo", "one_face_right_negative_space_left", "PEACE ISN'T BORING", "your body just forgot"),
            ("B", "emotional", "one_face_right_negative_space_left", "CALM FELT WRONG", "because chaos felt familiar"),
            ("C", "counter", "one_face_right_negative_space_left", "THE SPARK WAS ANXIETY", "not proof of love"),
        ]
    else:
        titles = [
            ("A", "seo", "specific scenario", working_title),
            ("B", "emotional", "curiosity gap", _safe_title(retention_hook or f"Why {topic} Still Hits Harder Than It Should", max_title_chars)),
            ("C", "counter", "counter-intuitive", _safe_title(core_claim or "It's Not About Them. It's About The Pattern", max_title_chars)),
        ]
        thumbs = [
            ("A", "seo", "one_face_right_negative_space_left", _clean_thumb_line1(only_soft_reset_line) or "THE REAL REASON", "here's what it costs"),
            ("B", "emotional", "one_face_right_negative_space_left", "YOU ALREADY KNOW", "you just won't admit it"),
            ("C", "counter", "one_face_right_negative_space_left", "YOU'RE NOT STUCK", "this is why you stay"),
        ]

    pillar_tags = {
        "relationship patterns": [
            "relationship advice", "dating advice", "situationship advice", "anxious attachment",
            "avoidant attachment", "trauma bonding", "love bombing signs", "emotional unavailability",
            "emotional storytelling", "reflective video",
            "why do i keep attracting the wrong person", "signs of anxious attachment in dating",
            "why am i always the one who cares more", "how to stop chasing unavailable people",
        ],
        "psychology drops": [
            "relationship advice", "emotional health", "self awareness", "attachment style",
            "psychology of love", "emotional intelligence", "why do i push away good people",
            "cinematic emotional video", "reflective video",
            "why does a good person feel boring", "signs you re used to chaos not love",
            "why don t i feel attracted to nice people", "am i addicted to chaos in relationships",
        ],
        "healing arcs": [
            "relationship advice", "breakup advice", "moving on after breakup", "emotional healing",
            "how to get over someone you love", "breakup recovery", "signs you re not over your ex",
            "emotional storytelling", "faceless video essay",
            "why does heartbreak feel like grief", "how to stop thinking about someone",
            "why do i still miss someone who hurt me", "moving on from a situationship",
        ],
        "self-worth shifts": [
            "relationship advice", "self worth", "personal growth", "know your worth",
            "setting boundaries in relationships", "stop settling in relationships",
            "emotional storytelling", "soft life",
            "why do i accept less than i deserve", "signs you have low self worth in relationships",
            "how to stop people pleasing in relationships", "why am i always the strong one",
            "how to stop shrinking yourself for others",
        ],
        "conversation truths": [
            "relationship advice", "communication in relationships", "dating advice",
            "healthy communication in relationships", "emotional honesty", "hard conversations",
            "reflective video", "emotional storytelling",
            "what to do when someone pulls away", "how to stop overthinking in relationships",
            "why do people go cold in relationships", "signs someone is losing interest",
        ],
        "identity and growth": [
            "relationship advice", "personal growth", "self worth", "emotional healing",
            "self improvement", "why do i lose myself in relationships",
            "faceless video essay", "emotional storytelling",
            "how to find yourself after a relationship", "signs you re emotionally unavailable",
            "why do i attract emotionally unavailable people", "becoming a better version of yourself",
        ],
    }
    base_tags = pillar_tags.get(pillar, [
        "relationship advice", "emotional healing", "personal growth", "dating advice",
        "why do i push away good people", "why does calm feel wrong in relationships",
        "how to stop chasing unavailable people", "signs you re used to chaos not love",
    ])
    seen: set[str] = set()
    tags: list[str] = []
    for t in ["soft reset with me", *base_tags]:
        if t not in seen:
            seen.add(t)
            tags.append(t)

    # Description: open with the sharpest line (only_soft_reset_line), not with core_claim
    opening_line = only_soft_reset_line or core_claim or viewer_pain or topic
    engagement_q = (
        f"Have you ever felt that pull away from someone just because they were actually steady? Drop it below."
        if not viewer_pain
        else f"Has this hit you somewhere specific? {viewer_pain[:80].rstrip()} — drop it below."
    )
    feeling_line = (
        "This is for the part of you that is tired of explaining why something still hurts."
    )
    description = (
        f"{opening_line}\n\n"
        f"{viewer_pain or topic}\n"
        f"{feeling_line}\n\n"
        f"{engagement_q}\n\n"
        "Subscribe for softer resets — @SoftResetWithMe\n\n"
        "#SoftResetWithMe #RelationshipAdvice #EmotionalHealing #HealingJourney #SelfWorth #EmotionalStorytelling"
    )

    title_list = [
        {"id": item[0], "angle": item[1], "formula": item[2], "title": _safe_title(item[3], max_title_chars)}
        for item in titles
    ]
    thumb_list = []
    for item in thumbs:
        line1 = _clean_thumb_line1(item[3])
        line2 = _clean_thumb_line2(item[4] if len(item) > 4 else "this is why it hurts")
        thumb_list.append({
            "id": item[0],
            "angle": item[1],
            "pattern": item[2],
            "line1": line1,
            "line2": line2,
            "thumbnail_text": _combine_thumb_copy(line1, line2),
        })
    primary = _pick_primary_variant(title_list, thumb_list)
    return {
        "primary_variant_id": primary,
        "description": description,
        "tags": tags,
        "title_variants": title_list,
        "thumbnail_variants": thumb_list,
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
        raw_line1 = item.get("line1", item.get("thumb_line1", ""))
        raw_line2 = item.get("line2", item.get("thumb_line2", ""))
        if raw_line1 or raw_line2:
            line1 = _clean_thumb_line1(raw_line1)
            line2 = _clean_thumb_line2(raw_line2)
        else:
            line1, line2 = _split_legacy_thumb_text(item.get("thumbnail_text", ""))
        text = _combine_thumb_copy(line1, line2)
        if vid in {"A", "B", "C"} and text:
            # Reject clinical thumbnail text — swap in fallback text for this variant
            if _thumb_text_is_clinical(text):
                fallback_thumb = next((t for t in fallback["thumbnail_variants"] if t["id"] == vid), None)
                if fallback_thumb:
                    print(f"[longform_metadata] Variant {vid} thumbnail text '{text}' is clinical — using fallback: '{fallback_thumb['thumbnail_text']}'")
                    line1 = fallback_thumb.get("line1", "")
                    line2 = fallback_thumb.get("line2", "")
                    text = fallback_thumb["thumbnail_text"]
            entry = {
                "id": vid,
                "angle": str(item.get("angle", "")).lower() or {"A": "seo", "B": "emotional_hook", "C": "counter_intuitive"}[vid],
                "pattern": str(item.get("pattern", "")).strip() or fallback["thumbnail_variants"][ord(vid) - 65]["pattern"],
                "line1": line1,
                "line2": line2,
                "thumbnail_text": text,
            }
            # Preserve AI-generated visual prompt if present; thumbnail agent can use it directly.
            ai_prompt = str(item.get("prompt", "")).strip()
            if ai_prompt:
                entry["visual_prompt"] = ai_prompt
            thumb_by_id[vid] = entry
    for item in fallback["thumbnail_variants"]:
        fb_entry = {k: v for k, v in item.items() if k != "prompt"}
        thumb_by_id.setdefault(item["id"], fb_entry)

    # Primary: never A; re-run smart picker using validated variants
    raw_primary = str(raw.get("primary_variant_id", "")).upper()
    if raw_primary == "A" or raw_primary not in {"A", "B", "C"}:
        primary_variant_id = _pick_primary_variant(
            [title_by_id[k] for k in ("A", "B", "C")],
            [thumb_by_id[k] for k in ("A", "B", "C")],
        )
    else:
        primary_variant_id = raw_primary

    # Deduplicate tags while preserving order
    raw_tags = raw.get("tags", fallback["tags"])
    seen: set[str] = set()
    deduped_tags: list[str] = []
    for t in (raw_tags if isinstance(raw_tags, list) else fallback["tags"]):
        tl = str(t).lower().strip()
        if tl and tl not in seen:
            seen.add(tl)
            deduped_tags.append(tl)

    return {
        "primary_variant_id": primary_variant_id,
        "description": str(raw.get("description", fallback["description"])).strip() or fallback["description"],
        "tags": deduped_tags or fallback["tags"],
        "title_variants": [title_by_id[key] for key in ("A", "B", "C")],
        "thumbnail_variants": [thumb_by_id[key] for key in ("A", "B", "C")],
    }


def run_longform_metadata(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_metadata] Building A/B packaging for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    hook = script.get("chapters", [{}])[0].get("voiceover", "") if script.get("chapters") else ""
    max_title_chars = int(config.get("max_title_chars", 70))
    from utils.strategy import inject_strategy
    template = inject_strategy(open("prompts/longform_packaging_prompt.txt").read(), "metadata")
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
