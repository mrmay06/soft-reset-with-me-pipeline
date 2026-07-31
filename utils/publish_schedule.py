from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def youtube_publish_at(config: dict, track: str, now: Optional[datetime] = None) -> Optional[str]:
    """Return the next configured ET publication time in YouTube's UTC format."""
    if not config.get("public_release_enabled", False):
        return None
    zone = ZoneInfo(config.get("timezone", "America/New_York"))
    local_now = (now or datetime.now(timezone.utc)).astimezone(zone)
    if track == "longform":
        target_time = config.get("target_publish_time_et", "12:00")
        days_ahead = (6 - local_now.weekday()) % 7  # Sunday
    else:
        target_time = config.get("target_publish_time_et", "20:00")
        days_ahead = 0
    hour, minute = (int(part) for part in target_time.split(":", 1))
    target = (local_now + timedelta(days=days_ahead)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if target <= local_now:
        target += timedelta(days=7 if track == "longform" else 1)
    return target.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
