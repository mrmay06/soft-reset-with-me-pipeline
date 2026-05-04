from __future__ import annotations

import re


DEFAULT_TAG_CHAR_LIMIT = 300
DEFAULT_TAG_COUNT_LIMIT = 15
MAX_TAG_LENGTH = 60
REQUIRED_TAGS = ("soft reset with me",)


def sanitize_youtube_tags(
    tags: list,
    total_char_limit: int = DEFAULT_TAG_CHAR_LIMIT,
    max_count: int = DEFAULT_TAG_COUNT_LIMIT,
) -> list[str]:
    clean = []
    total = 0
    seen = set()

    for tag in tags:
        value = re.sub(r"[^A-Za-z0-9 ]+", "", str(tag)).strip()
        value = re.sub(r"\s+", " ", value)[:MAX_TAG_LENGTH].strip()
        key = value.lower()
        if not value or key in seen:
            continue
        if len(clean) >= max_count:
            break
        if total + len(value) > total_char_limit:
            break
        clean.append(value)
        seen.add(key)
        total += len(value)

    return clean


def ensure_required_tags(tags: list) -> list:
    result = list(tags)
    existing = {str(tag).lower() for tag in result}
    for required in REQUIRED_TAGS:
        if required.lower() not in existing:
            result.append(required)
            existing.add(required.lower())
    return result
