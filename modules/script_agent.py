import os
import json

from utils.helpers import load_json, save_json, now_iso
from utils.gemini_client import generate_json, generate_text
from utils.retry import retry
from utils.script_contract import build_spoken_script_text, normalize_script_contract, word_count

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _call_script_model(prompt: str, model: str) -> dict:
    """Call Claude if model starts with 'claude-', else fall back to Gemini."""

    if model.startswith("claude-"):
        if _anthropic is None:
            raise RuntimeError("anthropic package not installed — run: pip install anthropic")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = _anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        text = message.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())

    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Script model returned non-object JSON")
    return result


_EGO_BAIT_SIGNALS = [
    "nobody tells you",
    "nobody told me",
    "most people",
    "99%",
    "i lost",
    "i paid",
    "i missed",
    "you've never heard",
    "quietly",
    "secretly",
    "they don't want you",
    "no one talks about",
    "most americans",
    "average person",
    "you're probably",
    "getting this wrong",
    "you didn't know",
]


def _hook_has_ego_bait(hook: str) -> bool:
    h = hook.lower()
    return any(sig in h for sig in _EGO_BAIT_SIGNALS)


def _validate_script(script: dict, config: dict) -> dict:
    script = normalize_script_contract(script)
    full_text = build_spoken_script_text(script)
    words = word_count(full_text)
    script["word_count"] = words

    min_w = config["script_min_words"]
    max_w = config["script_max_words"]

    if words < min_w or words > max_w:
        print(f"[script] Word count {words} outside {min_w}-{max_w} range — marking forced")
        script["validation"] = "forced"
    else:
        script["validation"] = "passed"

    # Hook quality check
    hook = script.get("hook", "")
    if not _hook_has_ego_bait(hook):
        print(f"[script] ⚠ Weak hook (no ego-bait pattern): '{hook}'")
        script["hook_quality"] = "weak"
    else:
        script["hook_quality"] = "strong"
        print(f"[script] ✓ Hook quality: strong")

    # Engagement question check
    eq = script.get("engagement_question", "")
    bad_generic = ["what do you think", "let me know", "comment your thoughts", "tell me below"]
    if not eq or any(phrase in eq.lower() for phrase in bad_generic):
        print(f"[script] ⚠ Generic engagement question: '{eq}' — flag for retry")
        script["engagement_quality"] = "weak"
    else:
        script["engagement_quality"] = "strong"
        print(f"[script] ✓ Engagement question: strong")

    return script


def run_script(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[script] Generating script for {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    prompt_template = open("prompts/script_prompt.txt").read()
    prompt = prompt_template.format(
        topic=research["topic"],
        category=research.get("category", ""),
        angle_type=research.get("angle_type", research.get("angle", "")),
        hook_seed=research.get("hook_seed", ""),
        source_fact=research.get("source_fact", ""),
        source_name=research.get("source_name", ""),
        video_id=video_id,
        generated_at=now_iso(),
    )

    script = _call_script_model(prompt, config["script_model"])
    script = _validate_script(script, config)

    if script["validation"] == "forced":
        print(f"[script] Retrying due to word count issue...")
        script = _call_script_model(prompt + "\n\nIMPORTANT: Script MUST be exactly 90-120 words.", config["script_model"])
        script = _validate_script(script, config)
        if script["validation"] != "passed":
            print("[script] Still outside range after retry — proceeding with forced validation")

    if script.get("hook_quality") == "weak":
        print(f"[script] Retrying hook for stronger pattern interrupt...")
        hook_prompt = (
            f"Rewrite ONLY the hook for this finance Short. Topic: {research['topic']}.\n"
            f"Current weak hook: '{script['hook']}'\n"
            f"Write ONE new hook under 12 words using EXACTLY ONE of these patterns:\n"
            f"- Direct accusation: 'Your [bank/employer/system] is [stealing/hiding] from you right now.'\n"
            f"- Massive number: 'You're losing $[specific odd number] a year and don't know it.'\n"
            f"- Contrarian: '[Popular belief] is the worst financial move you're making.'\n"
            f"Name the enemy. No warmup. No questions.\n"
            f"Return ONLY the hook text, no quotes, no explanation."
        )
        try:
            if config["script_model"].startswith("claude-"):
                if _anthropic is None:
                    raise RuntimeError("anthropic not installed")
                client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
                msg = client.messages.create(
                    model=config["script_model"],
                    max_tokens=64,
                    messages=[{"role": "user", "content": hook_prompt}],
                )
                new_hook = msg.content[0].text.strip().strip('"').strip("'")
            else:
                new_hook = generate_text(hook_prompt, config["script_model"]).strip('"').strip("'")
            if new_hook and len(new_hook.split()) <= 12:
                script["hook"] = new_hook
                script["hook_quality"] = "strong_retry"
                print(f"[script] ✓ Hook updated: '{new_hook}'")
        except Exception as e:
            print(f"[script] Hook retry failed ({e}) — keeping original")

    if script.get("engagement_quality") == "weak":
        print(f"[script] Retrying engagement question for stronger polarizer...")
        eq_prompt = (
            f"Write ONE polarizing engagement question for a YouTube Short on: {research['topic']}.\n"
            f"Rules: must force a pick-a-side response or personal confession. Be specific and opinionated.\n"
            f"Examples: 'Are you team 401k or team real estate? Fight me in the comments.'\n"
            f"         'Drop a 💰 if your employer matches and you're NOT maxing it.'\n"
            f"         'What's the dumbest money mistake you made this year?'\n"
            f"NOT acceptable: 'What do you think?' 'Let me know below.' 'Comment your thoughts.'\n"
            f"Return ONLY the question text, no quotes, no explanation."
        )
        try:
            if config["script_model"].startswith("claude-"):
                if _anthropic is None:
                    raise RuntimeError("anthropic not installed")
                client = _anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
                msg = client.messages.create(
                    model=config["script_model"],
                    max_tokens=80,
                    messages=[{"role": "user", "content": eq_prompt}],
                )
                new_eq = msg.content[0].text.strip().strip('"').strip("'")
            else:
                new_eq = generate_text(eq_prompt, config["script_model"]).strip('"').strip("'")
            if new_eq and len(new_eq.split()) >= 5:
                script["engagement_question"] = new_eq
                script["engagement_quality"] = "strong_retry"
                print(f"[script] ✓ Engagement question updated: '{new_eq}'")
        except Exception as e:
            print(f"[script] Engagement question retry failed ({e}) — keeping original")

    script = _validate_script(script, config)

    output_path = os.path.join(run_dir, "02_script.json")
    save_json(script, output_path)
    print(f"[script] Done. Words: {script['word_count']}, validation: {script['validation']}")
    return script


def run_script_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[script][MOCK] Generating mock script for {video_id}")
    result = {
        "video_id": video_id,
        "topic": "Pay your credit card twice a month to avoid interest",
        "category": "credit cards",
        "hook": "Most people never hear this.",
        "tension": "The average cardholder overpays because they misunderstand their statement cycle. The CFPB says most Americans don't even know when their billing cycle closes.",
        "insight": "Pay once before the statement date and once before the due date. This lowers your average daily balance — the number banks actually use to calculate interest. You could drop your interest charges to near zero without paying anything extra.",
        "loopback": "Most people still pay more than they need to.",
        "cta": "Tap the heart if this just saved you money.",
        "engagement_question": "Are you paying your credit card once a month? Drop a 💳 if you didn't know this trick.",
        "like_cta": "Tap the heart if this just saved you money.",
        "word_count": 102,
        "estimated_duration_sec": 41,
        "validation": "passed",
        "generated_at": now_iso(),
    }
    result = normalize_script_contract(result)
    output_path = os.path.join(run_dir, "02_script.json")
    save_json(result, output_path)
    print(f"[script][MOCK] Done.")
    return result
