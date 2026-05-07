from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from utils.helpers import load_json, save_json, now_iso

try:
    import anthropic
except ImportError:
    anthropic = None


PROPOSED_FILE = "strategy/strategy_memory_proposed.json"
REVIEWED_FILE = "strategy/strategy_memory_reviewed.json"


def _strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    return text.strip()


def _review_prompt(proposed: dict, comparison: dict, brand: dict) -> str:
    return f"""You are the final strategy reviewer for Soft Reset With Me Shorts.
Gemini has already drafted a weekly strategy update from Shorts analytics.

Your job:
- Keep useful, actionable changes.
- Remove or soften overfit conclusions from tiny samples.
- Preserve the same JSON schema and top-level keys.
- Do not invent performance data.
- Do not allow brand-bible conflicts.
- Prefer concise, operational guidance that future prompts can follow.
- If the proposal is already good, make only small edits.

BRAND BIBLE:
{json.dumps(brand, indent=2)[:5000]}

WEEKLY COMPARISON DATA:
{json.dumps(comparison, indent=2)[:9000]}

GEMINI PROPOSED STRATEGY:
{json.dumps(proposed, indent=2)}

Return ONLY the reviewed strategy JSON. No markdown, no commentary."""


def review_strategy(
    proposed_path: str = PROPOSED_FILE,
    reviewed_path: str = REVIEWED_FILE,
    comparison_path: str | None = None,
    model: str = "claude-sonnet-4-6",
) -> str:
    if not os.path.exists(proposed_path) and os.path.exists("strategy/strategy_memory.json"):
        proposed_path = "strategy/strategy_memory.json"
    proposed = load_json(proposed_path)
    if not isinstance(proposed, dict):
        raise RuntimeError(f"{proposed_path} must contain a JSON object")

    if anthropic is None or not os.environ.get("ANTHROPIC_API_KEY"):
        shutil.copyfile(proposed_path, reviewed_path)
        print("[strategy_reviewer] Anthropic unavailable; copied proposed strategy as reviewed")
        return reviewed_path

    comparison = {}
    if comparison_path and os.path.exists(comparison_path):
        comparison = load_json(comparison_path)
    brand = load_json("strategy/brand_bible.json") if os.path.exists("strategy/brand_bible.json") else {}

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": _review_prompt(proposed, comparison, brand)}],
    )
    reviewed = json.loads(_strip_json(message.content[0].text))
    reviewed["reviewed_at"] = now_iso()
    reviewed["review_model"] = model
    reviewed["review_source"] = "sonnet"
    save_json(reviewed, reviewed_path)

    version = reviewed.get("version") or proposed.get("version", "unversioned")
    history = Path(f"strategy/analysis_history/{version}_reviewed.json")
    history.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(reviewed_path, history)
    print(f"[strategy_reviewer] Wrote {reviewed_path} and archived {history}")
    return reviewed_path
