from __future__ import annotations

import re


SPOKEN_SECTION_KEYS = (
    "hook",
    "tension",
    "insight",
    "loopback",
    "engagement_question",
    "like_cta",
)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split())


def normalize_script_contract(script: dict) -> dict:
    """Keep legacy `cta` as an alias for the spoken like CTA only."""
    engagement_question = _clean_text(script.get("engagement_question", ""))
    like_cta = _clean_text(script.get("like_cta", ""))
    legacy_cta = _clean_text(script.get("cta", ""))

    if not like_cta:
        like_cta = legacy_cta
        if engagement_question and engagement_question in like_cta:
            like_cta = _clean_text(like_cta.replace(engagement_question, ""))

    script["engagement_question"] = engagement_question
    script["like_cta"] = like_cta
    script["cta"] = like_cta
    return script


def build_spoken_script_text(script: dict) -> str:
    normalized = normalize_script_contract(dict(script))
    return " ".join(
        normalized.get(key, "")
        for key in SPOKEN_SECTION_KEYS
        if normalized.get(key, "")
    ).strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'$%.-]+\b", text))
