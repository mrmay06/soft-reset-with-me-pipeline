from __future__ import annotations

import json
from pathlib import Path


MEMORY_FILES = [
    Path("topic_memory_soft_reset.json"),
    Path("performance_memory_soft_reset.json"),
    Path("topic_memory_soft_reset_long.json"),
    Path("performance_memory_soft_reset_long.json"),
    Path("strategy/strategy_memory.json"),
]

CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def _validate_file(path: Path) -> list[str]:
    errors: list[str] = []

    if not path.exists():
        return errors

    text = path.read_text()
    for marker in CONFLICT_MARKERS:
        if marker in text:
            errors.append(f"{path}: contains merge conflict marker {marker!r}")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        return errors

    if not isinstance(data, list):
        return errors

    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        video_id = item.get("video_id")
        if not isinstance(video_id, str) or not video_id:
            continue
        if video_id in seen:
            duplicates.add(video_id)
        seen.add(video_id)

    if duplicates:
        errors.append(f"{path}: duplicate video_id values: {', '.join(sorted(duplicates))}")

    return errors


def main() -> int:
    errors: list[str] = []
    for path in MEMORY_FILES:
        errors.extend(_validate_file(path))

    if errors:
        for error in errors:
            print(f"[memory-validate] ERROR: {error}")
        return 1

    print("[memory-validate] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
