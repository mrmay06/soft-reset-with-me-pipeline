import os
import json

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


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

    # Gemini fallback
    if genai is None:
        raise RuntimeError("google-generativeai not installed")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)


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
    full_text = " ".join([
        script.get("hook", ""),
        script.get("tension", ""),
        script.get("insight", ""),
        script.get("loopback", ""),
        script.get("cta", ""),
    ])
    word_count = len(full_text.split())
    script["word_count"] = word_count

    min_w = config["script_min_words"]
    max_w = config["script_max_words"]

    if word_count < min_w or word_count > max_w:
        print(f"[script] Word count {word_count} outside {min_w}-{max_w} range — marking forced")
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

    beat_visuals = script.get("beat_visuals", {})
    video_count = sum(1 for v in beat_visuals.values() if v == "video")
    image_count = sum(1 for v in beat_visuals.values() if v == "image")

    if image_count < 2:
        print("[script] Fixing beat_visuals: too few images, forcing beats 1+5 to image")
        script["beat_visuals"]["beat_1"] = "image"
        script["beat_visuals"]["beat_5"] = "image"
    if video_count < 1:
        print("[script] Fixing beat_visuals: no video beats, forcing beat_2 to video")
        script["beat_visuals"]["beat_2"] = "video"
    if video_count > 3:
        print("[script] Fixing beat_visuals: too many video beats, trimming to 3")
        count = 0
        for beat in ["beat_1", "beat_2", "beat_3", "beat_4", "beat_5"]:
            if script["beat_visuals"][beat] == "video":
                count += 1
                if count > 3:
                    script["beat_visuals"][beat] = "image"

    return script


def run_script(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[script] Generating script for {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    prompt_template = open("prompts/script_prompt.txt").read()
    prompt = prompt_template.format(
        topic=research["topic"],
        category=research["category"],
        angle=research["angle"],
        source_fact=research["source_fact"],
        source_name=research["source_name"],
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
        print(f"[script] Retrying hook for stronger ego-bait...")
        hook_prompt = (
            f"Rewrite ONLY the hook for this finance Short. Topic: {research['topic']}.\n"
            f"Current weak hook: '{script['hook']}'\n"
            f"Write ONE new hook under 10 words using one of these patterns:\n"
            f"- '99% of people don't know this...'\n"
            f"- 'Nobody tells you [truth]...'\n"
            f"- 'Most Americans get [topic] completely wrong...'\n"
            f"- 'This [thing] is quietly costing you...'\n"
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
                import google.generativeai as _g
                _g.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))
                resp = _g.GenerativeModel(config["script_model"]).generate_content(hook_prompt)
                new_hook = resp.text.strip().strip('"').strip("'")
            if new_hook and len(new_hook.split()) <= 15:
                script["hook"] = new_hook
                script["hook_quality"] = "strong_retry"
                print(f"[script] ✓ Hook updated: '{new_hook}'")
        except Exception as e:
            print(f"[script] Hook retry failed ({e}) — keeping original")

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
        "cta": "Save this.",
        "word_count": 102,
        "estimated_duration_sec": 41,
        "image_prompts": [
            "Bold minimalist graphic: large text '95%' in red on dark background, credit card icon, US-specific financial urgency",
            "Worried person sitting at desk with laptop and credit card statements, realistic photo style, warm indoor lighting",
            "Split calendar showing two payment dates highlighted in green, clean infographic style, white background",
            "Close-up of credit card interest calculation formula, numbers fading, clean flat design illustration",
            "Person smiling looking at phone with green checkmark notification, US home background, relief expression",
        ],
        "beat_visuals": {
            "beat_1": "image",
            "beat_2": "video",
            "beat_3": "image",
            "beat_4": "image",
            "beat_5": "video",
        },
        "thumbnail_prompt": "Dramatic close-up of credit card with large bold text overlay, dark background with red accent, high contrast",
        "thumbnail_text": "STOP OVERPAYING",
        "validation": "passed",
        "generated_at": now_iso(),
    }
    output_path = os.path.join(run_dir, "02_script.json")
    save_json(result, output_path)
    print(f"[script][MOCK] Done.")
    return result
