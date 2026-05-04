from __future__ import annotations

import re


DEFAULT_TAG_CHAR_LIMIT = 450
MAX_TAG_LENGTH = 30
REQUIRED_TAGS = ("US", "United States")


def sanitize_youtube_tags(tags: list, total_char_limit: int = DEFAULT_TAG_CHAR_LIMIT) -> list[str]:
    clean = []
    total = 0
    seen = set()

    for tag in tags:
        value = re.sub(r'[<>&"\']', "", str(tag)).strip()[:MAX_TAG_LENGTH]
        key = value.lower()
        if not value or key in seen:
            continue
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
