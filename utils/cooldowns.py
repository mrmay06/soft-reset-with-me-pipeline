from __future__ import annotations

from datetime import datetime, timezone


def active_cooldowns(strategy: dict) -> list[dict]:
    cooldowns = strategy.get("cooldowns", []) or strategy.get("research", {}).get("cooldowns", [])
    if not isinstance(cooldowns, list):
        return []
    today = datetime.now(timezone.utc).date()
    active = []
    for item in cooldowns:
        if not isinstance(item, dict):
            continue
        avoid_until = item.get("avoid_until")
        if not avoid_until:
            active.append(item)
            continue
        try:
            until = datetime.strptime(str(avoid_until)[:10], "%Y-%m-%d").date()
        except Exception:
            active.append(item)
            continue
        if until >= today:
            active.append(item)
    return active
