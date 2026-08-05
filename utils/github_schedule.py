from __future__ import annotations

from datetime import datetime


def _cron_hour(schedule_expression: str) -> int | None:
    """Return the UTC hour from a simple five-field GitHub cron expression."""
    fields = str(schedule_expression or "").split()
    if len(fields) != 5 or fields[0] != "0":
        return None
    try:
        hour = int(fields[1])
    except (TypeError, ValueError):
        return None
    return hour if 0 <= hour <= 23 else None


def _cron_day(schedule_expression: str) -> int | None:
    fields = str(schedule_expression or "").split()
    if len(fields) != 5 or fields[4] == "*":
        return None
    try:
        day = int(fields[4])
    except (TypeError, ValueError):
        return None
    return day if 0 <= day <= 6 else None


def scheduled_cron_matches_et(
    schedule_expression: str,
    now: datetime,
    target_hour_et: int = 6,
) -> bool:
    """Check whether the fired UTC cron is active for the target ET time."""
    cron_hour = _cron_hour(schedule_expression)
    if cron_hour is None or now.utcoffset() is None:
        return False
    cron_day = _cron_day(schedule_expression)
    if cron_day is not None and cron_day != (now.weekday() + 1) % 7:
        return False
    offset_hours = int(now.utcoffset().total_seconds() // 3600)
    expected_utc_hour = (target_hour_et - offset_hours) % 24
    return cron_hour == expected_utc_hour


def should_run(
    event_name: str,
    schedule_expression: str,
    now: datetime,
    automation_enabled: bool,
    target_hour_et: int = 6,
) -> tuple[bool, str]:
    """Return whether this workflow invocation should generate content."""
    if event_name != "schedule":
        return True, "manual_or_non_schedule_event"
    if not automation_enabled:
        return False, "automation_disabled"
    if not schedule_expression:
        return False, "missing_schedule_expression"
    if scheduled_cron_matches_et(schedule_expression, now, target_hour_et):
        return True, "active_dst_schedule"
    return False, "inactive_dst_schedule"
