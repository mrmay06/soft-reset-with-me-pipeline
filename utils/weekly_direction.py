from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


DEFAULT_PATH = Path("strategy/weekly_direction.json")


def load_weekly_direction(path: str | Path = DEFAULT_PATH) -> dict:
    """Return active, unexpired editorial direction; absence is a normal bypass."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or not data.get("active", False):
        return {}
    expires = str(data.get("expires_on", "")).strip()
    if expires:
        try:
            if date.today() > datetime.strptime(expires, "%Y-%m-%d").date():
                return {}
        except ValueError:
            return {}
    return data


def weekly_direction_prompt(path: str | Path = DEFAULT_PATH) -> str:
    direction = load_weekly_direction(path)
    if not direction:
        return ""
    priorities = direction.get("priorities", [])
    avoid = direction.get("avoid", [])
    notes = str(direction.get("notes", "")).strip()
    lines = ["OPTIONAL WEEKLY EDITORIAL DIRECTION (use as a preference, never as a blocker):"]
    lines.extend(f"- Prioritize: {item}" for item in priorities if str(item).strip())
    lines.extend(f"- Avoid: {item}" for item in avoid if str(item).strip())
    if notes:
        lines.append(f"- Notes: {notes}")
    return "\n".join(lines)
