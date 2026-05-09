"""
Strategy utilities: load active strategy context, inject into prompts,
determine experiment slot, and track strategy version per run.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timezone

from utils.cooldowns import active_cooldowns

STRATEGY_FILE = "strategy/strategy_memory.json"
BRAND_BIBLE_FILE = "strategy/brand_bible.json"


def get_strategy_version() -> str:
    """Return ISO week string e.g. '2026-W20'."""
    today = datetime.now(timezone.utc)
    iso = today.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def load_strategy() -> dict:
    if not os.path.exists(STRATEGY_FILE):
        return {}
    try:
        with open(STRATEGY_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def load_brand_bible() -> dict:
    if not os.path.exists(BRAND_BIBLE_FILE):
        return {}
    try:
        with open(BRAND_BIBLE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def get_strategy_context(section: str) -> str:
    """
    Return a formatted strategy context block for injection into a prompt.
    Returns empty string if strategy is untracked or section is empty.
    """
    strategy = load_strategy()
    if not strategy:
        return ""

    version = strategy.get("version", "untracked")
    if version == "untracked":
        return ""

    section_data = strategy.get(section)
    if not section_data:
        return ""
    if section == "research" and isinstance(section_data, dict):
        cooldowns = active_cooldowns(strategy)
        if cooldowns:
            section_data = {**section_data, "active_cooldowns": cooldowns}

    lines: list[str] = []

    def _has_content(data: dict) -> bool:
        return any(
            (isinstance(v, list) and v) or (isinstance(v, str) and v.strip())
            for v in data.values()
        )

    if not _has_content(section_data):
        return ""

    updated = (strategy.get("generated_at") or "")[:10]
    lines.append(f"STRATEGY CONTEXT (v{version}, updated {updated}):")

    for key, value in section_data.items():
        if isinstance(value, list) and value:
            label = key.upper().replace("_", " ")
            lines.append(f"\n{label}:")
            for item in value:
                lines.append(f"- {item}")
        elif isinstance(value, str) and value.strip():
            label = key.upper().replace("_", " ")
            lines.append(f"\n{label}: {value}")

    lines.append(
        "\nStrategy context is directional guidance from recent performance data. "
        "It does not override brand bible rules, safety rules, or content quality standards."
    )
    return "\n".join(lines)


def inject_strategy(prompt: str, section: str) -> str:
    """Append strategy context to a prompt string. No-op if context is empty."""
    ctx = get_strategy_context(section)
    if not ctx:
        return prompt
    return prompt + f"\n\n---\n{ctx}\n---"


def get_experiment_slot(workspace_dir: str = "workspace", track: str = "shorts") -> str:
    """
    Determine the experiment slot for this run: baseline, experiment, or wildcard.
    Target allocation: 60% baseline / 20% experiment / 20% wildcard.
    Looks at the last 20 judge reports for the given track.
    """
    strategy = load_strategy()
    if not strategy or strategy.get("version") == "untracked":
        return "baseline"

    pattern = "run_long_*" if track == "longform" else "run_2*"
    recent_dirs = sorted(glob.glob(os.path.join(workspace_dir, pattern)))[-20:]

    labels: list[str] = []
    for run_dir in recent_dirs:
        judge_path = os.path.join(run_dir, "10_judge_report.json")
        if os.path.exists(judge_path):
            try:
                with open(judge_path) as f:
                    labels.append(json.load(f).get("experiment_label", "baseline"))
            except Exception:
                pass

    if not labels:
        return "baseline"

    total = len(labels)
    baseline_pct = sum(1 for l in labels if l == "baseline") / total
    experiment_pct = sum(1 for l in labels if l == "experiment") / total
    wildcard_pct = sum(1 for l in labels if l == "wildcard") / total

    if baseline_pct >= 0.60:
        if experiment_pct < 0.20 and strategy.get("experiment_slots", {}).get("this_week"):
            return "experiment"
        if wildcard_pct < 0.20 and strategy.get("experiment_slots", {}).get("wildcard_slots"):
            return "wildcard"
    return "baseline"


def get_active_experiment_id(slot: str) -> str | None:
    """Return the experiment ID for the given slot from strategy memory, or None."""
    if slot == "baseline":
        return None
    strategy = load_strategy()
    slots = strategy.get("experiment_slots", {})
    pool = slots.get("this_week", []) if slot == "experiment" else slots.get("wildcard_slots", [])
    if pool and isinstance(pool[0], dict):
        return pool[0].get("id")
    return None
