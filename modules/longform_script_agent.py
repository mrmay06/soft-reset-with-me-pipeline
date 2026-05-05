from __future__ import annotations

import json
import os

from utils.gemini_client import generate_json
from utils.helpers import load_json, save_json, now_iso
from utils.performance_insights import summarize_performance_for_prompt
from utils.retry import retry
from utils.script_contract import word_count

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None


def _spoken_text(script: dict) -> str:
    return " ".join(ch.get("voiceover", "") for ch in script.get("chapters", [])).strip()


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _call_model(prompt: str, model: str) -> dict:
    if model.startswith("claude-"):
        if _anthropic is None:
            raise RuntimeError("anthropic package not installed")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = _anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Long-form script returned non-object JSON")
    return result


def _review_prompt(script: dict, research: dict) -> str:
    return f"""
You are the long-form editorial reviewer for Soft Reset With Me.
Check if this 5-7 minute script is a coherent emotional essay, not generic advice.

Core claim:
{research.get("core_claim", "")}

Script:
{json.dumps(script.get("chapters", []), indent=2)}

Review rules:
- The first chapter must clearly open the emotional loop.
- Every chapter must support the core claim.
- The middle must deepen the idea, not repeat the same point.
- The ending must land a soft reset, not a motivational slogan.
- Flag generic advice, therapy-speak bloat, or section drift.

Return ONLY valid JSON:
{{
  "passes": true,
  "issue_summary": "",
  "drift_chapters": [],
  "rewrite_instruction": ""
}}
""".strip()


def _review_script(script: dict, research: dict, config: dict) -> dict:
    if not config.get("script_argument_review_enabled", True):
        return {"passes": True, "status": "disabled"}
    try:
        review = _call_model(_review_prompt(script, research), config["script_model"])
        review["passes"] = bool(review.get("passes") and not review.get("drift_chapters"))
        review["status"] = "passed" if review["passes"] else "failed"
        return review
    except Exception as exc:
        return {"passes": True, "status": "soft_failed", "issue_summary": str(exc), "drift_chapters": []}


def _validate_script(script: dict, config: dict) -> dict:
    words = word_count(_spoken_text(script))
    script["word_count"] = words
    min_words = int(config.get("longform_target_words_min", 750))
    max_words = int(config.get("longform_target_words_max", 1050))
    estimated_duration = round(words / 155 * 60, 1) if words else 0
    script["estimated_duration_sec"] = estimated_duration
    warnings = []
    if words < min_words:
        warnings.append("too_short")
    if words > max_words:
        warnings.append("too_long")
    if len(script.get("chapters", [])) < 4:
        warnings.append("too_few_chapters")
    script["validation"] = "passed" if not warnings else "forced"
    script["validation_warnings"] = warnings
    return script


def run_longform_script(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_script] Writing script for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    template = open("prompts/longform_script_prompt.txt").read()
    performance_insights = summarize_performance_for_prompt(
        config.get("performance_memory_file", "performance_memory_soft_reset_long.json"),
        min_videos=int(config.get("performance_min_videos_for_prompt", 4)),
        pattern_min_videos=int(config.get("performance_pattern_min_videos", 12)),
        min_views=int(config.get("performance_min_views", 100)),
    )
    prompt = template.format(
        topic=research.get("topic", ""),
        working_title=research.get("working_title", ""),
        longform_format=research.get("longform_format", ""),
        content_pillar=research.get("content_pillar", ""),
        core_claim=research.get("core_claim", ""),
        editorial_seed=research.get("editorial_seed", ""),
        only_soft_reset_line=research.get("only_soft_reset_line", ""),
        viewer_pain=research.get("viewer_pain", ""),
        psych_concept=research.get("psych_concept", ""),
        retention_hook=research.get("retention_hook", ""),
        chapter_arc=json.dumps(research.get("chapter_arc", [])),
        visual_mood=research.get("visual_mood", ""),
        performance_insights=performance_insights,
        generated_at=now_iso(),
    )
    script = _call_model(prompt, config["script_model"])
    script["video_id"] = video_id
    script = _validate_script(script, config)
    review = _review_script(script, research, config)
    script["argument_review"] = review
    script["argument_quality"] = "strong" if review.get("passes") else "weak"

    if script["validation"] != "passed" or not review.get("passes"):
        retry_prompt = (
            prompt
            + "\n\nRewrite because validation/review failed.\n"
            + f"Validation warnings: {script.get('validation_warnings', [])}\n"
            + f"Review: {review}\n"
            + "Keep 750-1050 spoken words and make every chapter support the core claim."
        )
        script = _call_model(retry_prompt, config["script_model"])
        script["video_id"] = video_id
        script = _validate_script(script, config)
        review = _review_script(script, research, config)
        script["argument_review"] = review
        script["argument_quality"] = "strong" if review.get("passes") else "weak"

    script["generated_at"] = now_iso()
    save_json(script, os.path.join(run_dir, "02_longform_script.json"))
    print(f"[longform_script] Done. Words: {script.get('word_count', 0)}, review: {script.get('argument_quality')}")
    return script


def run_longform_script_mock(video_id: str, run_dir: str, config: dict) -> dict:
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    chapters = [
        {
            "id": 1,
            "label": "hook",
            "purpose": "open loop",
            "voiceover": (
                "If you keep missing someone who barely showed up, this might be why. "
                "You may not be missing the relationship. You may be missing the future your hope kept rehearsing. "
                "That is why the grief feels confusing. The facts say they were inconsistent. Your body says you lost something huge. "
                "Both can be true. You can know someone was not steady, and still feel shaken when the fantasy finally ends."
            ),
        },
        {
            "id": 2,
            "label": "name the pain",
            "purpose": "separate person from potential",
            "voiceover": (
                "This kind of heartbreak has a strange shape. You are not only replaying what happened. You are replaying what almost happened. "
                "The almost apology. The almost commitment. The almost version of them who finally understood how carefully you were trying. "
                "That almost can become addictive because it gives your mind somewhere to go. It says, maybe if I had waited longer, explained better, stayed softer, they would have become who I needed. "
                "But love cannot live on almost forever. At some point, almost becomes a room you keep entering even though there is nothing new inside."
            ),
        },
        {
            "id": 3,
            "label": "hidden pattern",
            "purpose": "explain rehearsed future",
            "voiceover": (
                "Your mind is very good at completing unfinished stories. When someone gives you warmth and distance in the same relationship, your nervous system starts looking for the pattern. "
                "It remembers the good night texts. It remembers the one honest conversation. It remembers the way they looked at you when things felt possible. "
                "Then it quietly edits around the silence, the confusion, the cancelled plans, and the moments where you had to shrink your needs to keep the connection alive. "
                "That edit is not stupidity. It is hope trying to protect itself from disappointment. It keeps saying, this could still become something beautiful."
            ),
        },
        {
            "id": 4,
            "label": "reframe",
            "purpose": "release fantasy",
            "voiceover": (
                "The soft reset is not to shame yourself for believing in them. There was probably something real enough to touch your heart. "
                "The reset is learning to separate evidence from imagination. Evidence is what someone does repeatedly. Imagination is what you believe they might do if everything finally lines up. "
                "You can grieve the imagination without handing it the keys again. You can miss the sweetness without ignoring the instability. "
                "And you can admit that a person had beautiful moments without turning those moments into a future they never actually chose."
            ),
        },
        {
            "id": 5,
            "label": "soft reset",
            "purpose": "close",
            "voiceover": (
                "So if you miss them tonight, try asking a cleaner question. Do I miss who they were, or who I kept hoping they would become? "
                "That question will not erase the ache. But it may put the ache in the right place. "
                "You are allowed to grieve the version they never became. You are allowed to feel sad about the future you pictured. "
                "Just do not confuse that grief with a sign that you should go back. Sometimes the most loving thing you can do for yourself is stop waiting for potential to become proof."
            ),
        },
        {
            "id": 6,
            "label": "what changes now",
            "purpose": "give the viewer a grounded practice",
            "voiceover": (
                "The next time your mind starts rebuilding them, slow the story down. Name one thing they consistently did, not one thing they occasionally promised. "
                "Name one moment where your body felt peaceful, and one moment where your body felt like it was auditioning for love. "
                "This is not about making them the villain. It is about letting reality be specific enough to protect you. "
                "A person can have tenderness and still not have capacity. A connection can be intense and still not be safe to build your life around. "
                "When you can hold both truths at the same time, you stop needing the fantasy to explain the pain. "
                "You also stop bargaining with yourself. You stop saying, maybe I asked for too much, when what you asked for was steadiness. "
                "You stop calling confusion chemistry. You stop mistaking emotional hunger for proof that this person was home."
            ),
        },
        {
            "id": 7,
            "label": "closing note",
            "purpose": "soft emotional landing",
            "voiceover": (
                "One day, you may look back and realize the hardest part was not losing them. It was forgiving yourself for believing so deeply in what they could have been. "
                "Be gentle there. Hope is not a character flaw. It only becomes a trap when it keeps asking you to ignore what is already clear. "
                "So let yourself miss the dream. Let yourself mourn the almost. Then come back to the life that is actually asking for you. "
                "Soft does not mean you wait forever. Sometimes soft means you finally stop abandoning yourself for a maybe. "
                "And if this is where you are tonight, you do not have to solve the whole grief at once. "
                "Just tell the truth gently. I miss what I imagined, and I am ready to stop building my future around someone else's potential. "
                "That sentence is small, but it can be the first door back to yourself."
            ),
        },
    ]
    script = {
        "video_id": video_id,
        "topic": research["topic"],
        "working_title": research["working_title"],
        "content_pillar": research["content_pillar"],
        "longform_format": research["longform_format"],
        "core_claim": research["core_claim"],
        "editorial_pov": research["editorial_seed"],
        "only_soft_reset_line": research["only_soft_reset_line"],
        "chapters": chapters,
        "visual_brief": [
            {"chapter_id": 1, "scene_role": "hook", "stock_queries": ["rainy window night", "person alone window", "city night apartment"], "image_prompt": ""},
            {"chapter_id": 2, "scene_role": "tension", "stock_queries": ["empty chair room", "person sitting alone", "quiet bedroom"], "image_prompt": ""},
            {"chapter_id": 3, "scene_role": "pattern", "stock_queries": ["hands journal", "walking city night", "train window night"], "image_prompt": ""},
            {"chapter_id": 4, "scene_role": "reframe", "stock_queries": ["candlelit room", "closing journal", "morning window"], "image_prompt": ""},
            {"chapter_id": 5, "scene_role": "reset", "stock_queries": ["city walk evening", "open window curtains", "quiet sunrise room"], "image_prompt": ""},
            {"chapter_id": 6, "scene_role": "practice", "stock_queries": ["hands writing journal", "person walking alone", "apartment window"], "image_prompt": ""},
            {"chapter_id": 7, "scene_role": "closing", "stock_queries": ["quiet sunrise room", "city walk evening", "open window curtains"], "image_prompt": ""}
        ],
        "cta": "Subscribe for softer resets.",
        "argument_review": {"passes": True, "status": "mock"},
        "argument_quality": "strong",
        "generated_at": now_iso(),
    }
    script = _validate_script(script, config)
    save_json(script, os.path.join(run_dir, "02_longform_script.json"))
    print(f"[longform_script][MOCK] Done. Words: {script['word_count']}")
    return script
