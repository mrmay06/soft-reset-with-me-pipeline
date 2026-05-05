import os
import json

from utils.helpers import load_json, save_json, now_iso
from utils.gemini_client import generate_json, generate_text
from utils.retry import retry
from utils.script_contract import build_spoken_script_text, normalize_script_contract, word_count
from utils.performance_insights import summarize_performance_for_prompt

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
    "left you on read",
    "watched your story",
    "text again",
    "double text",
    "calmest reply",
    "strongest boundary",
    "overexplaining",
    "not love",
    "not communication",
    "you did not lose",
    "you didn't lose",
    "moving on fast",
    "soft does not mean weak",
    "talking every day",
    "if you've ever",
    "if you",
    "this is for you",
    "most people think",
    "you think",
    "might be",
    "might not be",
    "not intuitive",
    "not intuition",
    "triggered",
    "late reply",
    "ruins your mood",
    "silence makes you",
    "red flag",
    "old pain",
    "old wound",
    "gut feeling",
]


_WEAK_ABSTRACT_HOOK_PATTERNS = [
    "nervous system remembers",
    "mind calls intuition",
    "healing starts",
    "listen to yourself",
    "hardest lessons",
    "old pain wearing",
]


_GENERIC_EDITORIAL_PATTERNS = [
    "love yourself",
    "you are enough",
    "validate your feelings",
    "healthy relationships are important",
    "communication is key",
    "set boundaries",
    "move on",
    "healing takes time",
]


def _hook_has_ego_bait(hook: str) -> bool:
    h = hook.lower()
    if any(pattern in h for pattern in _WEAK_ABSTRACT_HOOK_PATTERNS):
        return False
    return any(sig in h for sig in _EGO_BAIT_SIGNALS)


def _validate_editorial_layer(script: dict) -> bool:
    pov = str(script.get("editorial_pov", "") or "").strip()
    signature = str(script.get("only_soft_reset_line", "") or "").strip()
    if len(pov.split()) < 8 or len(signature.split()) < 6:
        return False
    combined = f"{pov} {signature}".lower()
    return not any(pattern in combined for pattern in _GENERIC_EDITORIAL_PATTERNS)


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

    if not _validate_editorial_layer(script):
        print("[script] ⚠ Weak editorial layer: missing POV or signature Soft Reset line")
        script["editorial_quality"] = "weak"
        script["validation"] = "forced"
    else:
        script["editorial_quality"] = "strong"
        print("[script] ✓ Editorial layer: strong")

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
    performance_insights = summarize_performance_for_prompt(
        config.get("performance_memory_file", "performance_memory_soft_reset.json"),
        min_videos=int(config.get("performance_min_videos_for_prompt", 8)),
        pattern_min_videos=int(config.get("performance_pattern_min_videos", 25)),
        min_views=int(config.get("performance_min_views", 50)),
    )
    prompt = prompt_template.format(
        topic=research["topic"],
        category=research.get("category", ""),
        angle_type=research.get("angle_type", research.get("angle", "")),
        hook_seed=research.get("hook_seed", ""),
        source_fact=research.get("source_fact", ""),
        source_basis=research.get("source_basis", research.get("source_fact", "")),
        source_name=research.get("source_name", ""),
        content_format=research.get("content_format", "scenario"),
        emotional_trigger=research.get("emotional_trigger", ""),
        psych_concept=research.get("psych_concept", ""),
        core_claim=research.get("core_claim", ""),
        editorial_seed=research.get("editorial_seed", ""),
        only_soft_reset_line=research.get("only_soft_reset_line", ""),
        performance_insights=performance_insights,
        video_id=video_id,
        generated_at=now_iso(),
    )

    script = _call_script_model(prompt, config["script_model"])
    script = _validate_script(script, config)

    if script["validation"] == "forced":
        print(f"[script] Retrying due to validation issue...")
        retry_prompt = (
            prompt
            + "\n\nIMPORTANT: Script MUST be 45-75 words and must include "
            "`editorial_pov` plus `only_soft_reset_line` that are specific, non-generic, and on-brand."
        )
        script = _call_script_model(retry_prompt, config["script_model"])
        script = _validate_script(script, config)
        if script["validation"] != "passed":
            print("[script] Still outside range after retry — proceeding with forced validation")

    if script.get("hook_quality") == "weak":
        print(f"[script] Retrying hook for stronger pattern interrupt...")
        hook_prompt = (
            f"Rewrite ONLY the hook for this relationship self-improvement Short. Topic: {research['topic']}.\n"
            f"Current weak hook: '{script['hook']}'\n"
            f"Write ONE new scroll-stopping hook under 12 words in the Soft Reset With Me voice.\n"
            f"Use plain words, not poetic phrasing. The viewer should instantly think, 'wait, is this about me?'\n"
            f"Best patterns:\n"
            f"- 'You think it is intuition. It might be trauma.'\n"
            f"- 'If one late reply ruins your mood, this is for you.'\n"
            f"- 'You might be triggered, not intuitive.'\n"
            f"- 'That panic might not be a red flag.'\n"
            f"- 'If silence makes you feel abandoned, listen to this.'\n"
            f"No warmup. No diagnosis. No hype coach language.\n"
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
            f"Rules: must fit Soft Reset With Me. Ask for a save, share, comment, or honest confession.\n"
            f"Examples: 'Which one hit hardest?'\n"
            f"         'Save this for when you start missing their potential.'\n"
            f"         'Agree or disagree?'\n"
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
        "topic": "You did not lose them, you lost who you imagined they would be",
        "category": "healing arcs",
        "content_format": "truth_drop",
        "emotional_trigger": "grieving someone's potential",
        "psych_concept": "idealization and grief",
        "core_claim": "You are grieving the imagined future more than the person.",
        "editorial_pov": "Missing someone is not always proof they were right for you. Sometimes it proves how much hope you built around them.",
        "only_soft_reset_line": "You are allowed to grieve the version they never became.",
        "hook": "You did not lose them. You lost who you imagined.",
        "tension": "That is why it still hurts. You are grieving a version that never arrived.",
        "insight": "You miss the apology they almost gave. The effort they almost made. That was not love. That was hope with someone else's face on it.",
        "loopback": "Grieve the dream. Do not chase the person.",
        "cta": "Save this for when you start missing their potential.",
        "engagement_question": "Which hurts more: missing them, or missing who you imagined?",
        "like_cta": "Save this for when you start missing their potential.",
        "thumbnail_text": "YOU LOST THE DREAM",
        "word_count": 67,
        "estimated_duration_sec": 25,
        "validation": "passed",
        "generated_at": now_iso(),
    }
    result = normalize_script_contract(result)
    output_path = os.path.join(run_dir, "02_script.json")
    save_json(result, output_path)
    print(f"[script][MOCK] Done.")
    return result
