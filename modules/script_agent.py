from __future__ import annotations

import os
import json
import re

from utils.helpers import load_json, save_json, now_iso
from utils.gemini_client import generate_json
from utils.ai_usage import measured_call
from utils.claude_response import request_options, response_text
from utils.retry import retry
from utils.script_contract import build_spoken_script_text, normalize_script_contract, word_count, spoken_text_hash, quote_is_spoken
from utils.performance_insights import summarize_performance_for_prompt
from utils.strategy import inject_strategy

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
        message = measured_call("anthropic", model, "script_or_review", client.messages.create,
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            **request_options(model),
        )
        text = response_text(message)
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


_WEAK_ABSTRACT_HOOK_PATTERNS = [
    "nervous system remembers",
    "mind calls intuition",
    "healing starts",
    "listen to yourself",
    "hardest lessons",
    "old pain wearing",
]


_OBSERVABLE_HOOK_SIGNALS = [
    "type the",
    "delete the",
    "replace it",
    "late reply",
    "rereading",
    "checking",
    "last-seen",
    "last seen",
    "rehearse the",
    "say nothing",
    "ask for space",
    "phone",
    "message",
    "backspace",
]


_HOOK_ACTION_WORDS = {
    "ask", "apologize", "call", "check", "choose", "delete", "disappear", "edit",
    "feel", "hide", "keep", "lose", "make", "pretend", "pull", "read", "rehearse",
    "replace", "reread", "say", "scroll", "shrink", "text", "think", "type", "wait",
}


# A visible action + object is a concrete scene even without "but/because".
# Include ordinary verb forms rather than requiring one exact stock phrase.
_HOOK_SCENE_ACTION_WORDS = {
    "open", "opens", "opened", "opening",
    "zoom", "zooms", "zoomed", "zooming",
    "look", "looks", "looked", "looking",
    "study", "studies", "studied", "studying",
    "hover", "hovers", "hovered", "hovering",
    "scroll", "scrolls", "scrolled", "scrolling",
    "tap", "taps", "tapped", "tapping",
}
_HOOK_SCENE_OBJECT_WORDS = {
    "profile", "photo", "photos", "picture", "pictures", "smile",
    "caption", "captions", "screen", "post", "posts", "feed",
    "notification", "notifications", "conversation", "chat", "draft", "cursor",
}


_HOOK_CONTRADICTION_SIGNALS = (
    " but ", " so ", " then ", " when ", " after ", " because ", " until ",
    " instead ", " not ",
)


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


_BANNED_SCRIPT_PHRASES = [
    "you are enough",
    "love yourself first",
    "hi guys",
    "so basically",
    "your feelings are valid",
    "that's valid",
    "it's valid to feel",
    "healing journey",
    "healing takes time",
    "do the work",
    "show up for yourself",
]


_BANNED_LOOPBACK_PHRASES = [
    "you deserve better",
    "you are enough",
    "your feelings are valid",
    "healing takes time",
    "your exhaustion is valid",
    "you deserve support",
]


_BANNED_RETENTION_FILLER = [
    "stay with me",
    "don't leave yet",
    "do not leave yet",
    "what comes next changes everything",
    "the next part changes everything",
]


_UNSUPPORTED_GUARANTEE_PATTERNS = [
    "the right person will",
    "the right person won't",
    "the problem was never you",
    "nobody falls for",
    "they were never going to",
]


_SUPERIORITY_FRAMING_PATTERNS = [
    "can't hold depth",
    "cannot hold depth",
    "couldn't handle you",
    "could not handle you",
    "someone else's low ceiling",
    "their low ceiling",
    "not on your level",
    "beneath you",
    "too deep for them",
    "they lack capacity",
    "their limited capacity",
]


_GENERIC_CTA_PATTERNS = [
    "save this one",
    "send this to someone who",
    "share this with someone who",
]


def _hook_is_specific(hook: str) -> bool:
    h = hook.lower().replace("’", "'")
    if any(pattern in h for pattern in _WEAK_ABSTRACT_HOOK_PATTERNS):
        return False
    if any(sig in h for sig in _OBSERVABLE_HOOK_SIGNALS):
        return True
    words = re.findall(r"[a-z']+", h)
    word_set = set(words)
    has_viewer = bool(word_set & {"you", "your", "you're", "you've", "you'd", "you'll"})
    if (has_viewer and word_set & _HOOK_SCENE_ACTION_WORDS
            and word_set & _HOOK_SCENE_OBJECT_WORDS):
        return True
    has_action = bool(set(words) & _HOOK_ACTION_WORDS)
    has_contradiction = any(signal in f" {h} " for signal in _HOOK_CONTRADICTION_SIGNALS)
    return 4 <= len(words) <= 22 and has_viewer and has_action and has_contradiction


def _hook_has_ego_bait(hook: str) -> bool:
    """Backward-compatible alias for the former keyword-only hook check."""
    return _hook_is_specific(hook)


def _contains_any(text: str, phrases: list[str]) -> list[str]:
    lower = text.lower()
    return [phrase for phrase in phrases if phrase in lower]


def _validate_editorial_layer(script: dict) -> bool:
    pov = str(script.get("editorial_pov", "") or "").strip()
    signature = str(script.get("only_soft_reset_line", "") or "").strip()
    if len(pov.split()) < 8 or len(signature.split()) < 6:
        return False
    combined = f"{pov} {signature}".lower()
    return not any(pattern in combined for pattern in _GENERIC_EDITORIAL_PATTERNS)


def _validate_script(script: dict, config: dict) -> dict:
    script = normalize_script_contract(script)
    incoming_validation = str(script.get("validation", "") or "").strip().lower()
    script.setdefault("script_version", "1")
    script.setdefault("prompt_version", "soft-reset-script-v2.7")
    script.setdefault("validation_notes", "")

    full_text = build_spoken_script_text(script)
    words = word_count(full_text)
    script["word_count"] = words
    validation_notes = []
    validation_failures = []

    min_w = config["script_min_words"]
    max_w = config["script_max_words"]
    hard_min_w = config.get("script_hard_min_words", max(1, min_w - 10))
    hard_max_w = config.get("script_hard_max_words", max_w + 20)

    if words < min_w or words > max_w:
        print(f"[script] Word count {words} outside target {min_w}-{max_w} range — soft warning")
        script["validation"] = "passed"
        validation_notes.append(f"word_count outside target {min_w}-{max_w}")
    else:
        script["validation"] = "passed"

    if words < hard_min_w or words > hard_max_w:
        print(f"[script] Word count {words} outside hard {hard_min_w}-{hard_max_w} limit — marking forced")
        script["validation"] = "forced"
        validation_failures.append("word_count_hard")
        validation_notes.append(f"word_count outside hard limit {hard_min_w}-{hard_max_w}")

    if incoming_validation == "needs_review" and script["validation"] == "passed":
        script["validation"] = "needs_review"
        validation_notes.append(str(script.get("validation_notes", "") or "model requested review"))

    banned_hits = _contains_any(full_text, _BANNED_SCRIPT_PHRASES)
    if banned_hits:
        print(f"[script] ⚠ Banned script phrase(s): {banned_hits}")
        script["validation"] = "forced"
        validation_failures.append("banned_script_phrase")
        validation_notes.append(f"banned phrases: {', '.join(banned_hits)}")

    loopback_hits = _contains_any(str(script.get("loopback", "")), _BANNED_LOOPBACK_PHRASES)
    if loopback_hits:
        print(f"[script] ⚠ Banned loopback phrase(s): {loopback_hits}")
        script["validation"] = "forced"
        validation_failures.append("banned_loopback")
        validation_notes.append(f"banned loopback: {', '.join(loopback_hits)}")

    retention_hits = _contains_any(full_text, _BANNED_RETENTION_FILLER)
    if retention_hits:
        print(f"[script] ⚠ Retention filler phrase(s): {retention_hits}")
        script["validation"] = "forced"
        validation_failures.append("retention_filler")
        validation_notes.append(f"retention filler: {', '.join(retention_hits)}")

    guarantee_hits = _contains_any(full_text, _UNSUPPORTED_GUARANTEE_PATTERNS)
    if guarantee_hits:
        print(f"[script] ⚠ Unsupported guarantee phrase(s): {guarantee_hits}")
        script["validation"] = "forced"
        validation_failures.append("unsupported_guarantee")
        validation_notes.append(f"unsupported guarantees: {', '.join(guarantee_hits)}")

    superiority_hits = _contains_any(full_text, _SUPERIORITY_FRAMING_PATTERNS)
    if superiority_hits:
        print(f"[script] ⚠ Superiority framing phrase(s): {superiority_hits}")
        script["validation"] = "forced"
        validation_failures.append("superiority_framing")
        validation_notes.append(f"superiority framing: {', '.join(superiority_hits)}")

    cta_text = " ".join(
        str(script.get(key, "") or "")
        for key in ("engagement_question", "like_cta", "cta")
    )
    generic_cta_hits = _contains_any(cta_text, _GENERIC_CTA_PATTERNS)
    if generic_cta_hits:
        print(f"[script] ⚠ Generic or call-out CTA phrase(s): {generic_cta_hits}")
        script["validation"] = "forced"
        validation_failures.append("generic_cta")
        validation_notes.append(f"generic CTA: {', '.join(generic_cta_hits)}")

    if not _validate_editorial_layer(script):
        print("[script] ⚠ Weak editorial layer: missing POV or signature Soft Reset line")
        script["editorial_quality"] = "weak"
        script["validation"] = "forced"
        validation_failures.append("weak_editorial_layer")
        validation_notes.append("weak editorial layer")
    else:
        script["editorial_quality"] = "strong"
        print("[script] ✓ Editorial layer: strong")

    # Hook quality check
    hook = script.get("hook", "")
    if not _hook_is_specific(hook):
        print(f"[script] ⚠ Weak hook (not concrete or structurally specific): '{hook}'")
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

    script["validation_failures"] = validation_failures
    script["word_count_in_range"] = min_w <= words <= max_w
    script["word_count_hard_limit"] = hard_min_w <= words <= hard_max_w
    script["validation_notes"] = "; ".join(validation_notes)
    return script




def _mark_needs_review(script: dict, reason: str) -> dict:
    notes = str(script.get("validation_notes", "") or "").strip()
    script["validation"] = "needs_review"
    script["human_review_required"] = True
    script["validation_notes"] = f"{notes}; {reason}".strip("; ")
    return script


def _argument_review_prompt(script: dict, research: dict) -> str:
    sections = {
        "hook": script.get("hook", ""),
        "tension": script.get("tension", ""),
        "insight": script.get("insight", ""),
        "loopback": script.get("loopback", ""),
    }
    return f"""
You are the human editorial review layer for Soft Reset With Me.
Judge whether this YouTube Short has a real argument or slips into generic relationship advice.

Core claim:
{research.get("core_claim", "")}

Editorial seed:
{research.get("editorial_seed", "")}

Spoken script sections (the complete narration):
{json.dumps(sections, indent=2)}

Review rules:
- The hook promise must match the payoff.
- Every spoken section must actively support the core claim.
- Judge only the narration. Research notes are intended direction, not evidence that the video delivers it. The signature line must be present in a spoken section; do not credit an unspoken annotation.
- Flag any section that becomes neutral explainer mode, generic advice, or filler.
- The signature line must feel specific to Soft Reset With Me, not a generic self-help phrase.
- Psychological causes must be calibrated as possibilities unless the script has direct evidence.
- Ordinary feelings, illustrative scenes, and emotional interpretations do not need citations. Do not fail them for lacking a source. Reject invented research, statistics, diagnoses, and unsupported biological explanations.
- The script must preserve viewer agency without blaming the viewer or guaranteeing how another person will behave.
- Do not preserve agency by flattering the viewer as deeper, wiser, or more capable while declaring the other person shallow, incapable, or beneath them.
- Be strict, but do not fail a script just because it is simple.

Return ONLY valid JSON:
{{
  "passes": true,
  "hook_promise_matches": true,
  "sections_support_core_claim": true,
  "generic_drift_sections": [],
  "signature_line_distinctive": true,
  "signature_line_quote": "exact quote from a spoken section",
  "psychological_claims_calibrated": true,
  "viewer_agency_preserved": true,
  "fairness_preserved": true,
  "issue_summary": "",
  "rewrite_instruction": ""
}}
""".strip()


def _check_argument_coherence(script: dict, research: dict, config: dict) -> dict:
    if not config.get("script_argument_review_enabled", True):
        return {
            "passes": True,
            "status": "disabled",
            "spoken_text_sha256": spoken_text_hash(build_spoken_script_text(script)),
            "issue_summary": "",
            "rewrite_instruction": "",
        }
    try:
        review = _call_script_model(_argument_review_prompt(script, research), config["script_model"])
        if not isinstance(review, dict):
            raise ValueError("argument review returned non-object JSON")
        passes = (
            review.get("passes") is True
            and review.get("hook_promise_matches") is True
            and review.get("sections_support_core_claim") is True
            and review.get("signature_line_distinctive") is True
            and quote_is_spoken(review.get("signature_line_quote"), build_spoken_script_text(script))
            and review.get("psychological_claims_calibrated") is True
            and review.get("viewer_agency_preserved") is True
            and review.get("fairness_preserved") is True
            and review.get("generic_drift_sections") == []
        )
        review["passes"] = bool(passes)
        review["status"] = "passed" if passes else "failed"
        review["spoken_text_sha256"] = spoken_text_hash(build_spoken_script_text(script))
        return review
    except Exception as exc:
        return {
            "passes": False,
            "status": "unavailable",
            "issue_summary": f"Argument review failed: {exc}",
            "rewrite_instruction": "",
        }


def _attach_argument_review(script: dict, review: dict) -> dict:
    script["argument_review"] = review
    if review.get("passes"):
        script["argument_quality"] = "strong" if review.get("status") != "soft_failed" else "unknown"
        print(f"[script] ✓ Argument coherence: {review.get('status', 'passed')}")
    else:
        script["argument_quality"] = "weak"
        script["validation"] = "forced"
        print(f"[script] ⚠ Argument coherence failed: {review.get('issue_summary', '')}")
    return script


def _require_available_argument_review(script: dict, run_dir: str) -> None:
    if script.get("argument_review", {}).get("status") == "unavailable":
        _mark_needs_review(script, "argument review unavailable; retry review before media generation")
        save_json(script, os.path.join(run_dir, "02_script.json"))
        raise RuntimeError("Script argument review unavailable; saved script for review retry.")


def _log_final_state(script: dict) -> None:
    print(
        "[script] Final state — "
        f"validation: {script.get('validation', '')} | "
        f"hook: {script.get('hook_quality', '')} | "
        f"editorial: {script.get('editorial_quality', '')} | "
        f"argument: {script.get('argument_quality', '')} | "
        f"engagement: {script.get('engagement_quality', '')} | "
        f"words: {script.get('word_count', 0)}"
    )


def _bounded_script_generation(prompt: str, research: dict, config: dict, run_dir: str) -> dict:
    """Three drafts, two editorial reviews; no post-approval edits."""
    review_count = 0
    revision_prompt = prompt
    for draft_count in range(1, 4):
        script = _validate_script(_call_script_model(revision_prompt, config["script_model"]), config)
        script["generation_attempts"] = {"drafts": draft_count, "reviews": review_count}
        issues = list(script.get("validation_failures", []))
        if script.get("hook_quality") == "weak":
            issues.append("weak_hook")
        if script.get("engagement_quality") == "weak":
            issues.append("weak_engagement_question")
        if script.get("validation") == "needs_review" or script.get("human_review_required"):
            issues.append("human_review_required")
        target_warning = not script.get("word_count_in_range", True)
        review = {}
        # Target word range remains a preference; existing hard limits still
        # block. Spend a correction on it only while a draft is available.
        if not issues and (not target_warning or draft_count == 3):
            review = _check_argument_coherence(script, research, config)
            review_count += 1
            script["generation_attempts"]["reviews"] = review_count
            script = _attach_argument_review(script, review)
            _require_available_argument_review(script, run_dir)
            if review.get("passes") is True:
                return script
            issues.append("argument_review_failed")
        if draft_count == 3 or review_count == 2:
            script = _mark_needs_review(script, "bounded script correction budget exhausted: " + ", ".join(issues))
            save_json(script, os.path.join(run_dir, "02_script.json"))
            raise RuntimeError("Script correction budget exhausted; saved draft needs review before media generation")
        revision_prompt = (
            prompt + "\n\nCOMBINED CORRECTION: revise the whole JSON script once, addressing ALL issues together.\n"
            + f"Issues: {issues}; target word range warning: {target_warning}.\n"
            + f"Prefer {config['script_min_words']}-{config['script_max_words']} spoken words. Preserve the same core claim.\n"
            + "Use a concrete, plain-language opening and a specific, natural engagement question. "
            "No diagnosis, superiority framing, guarantees, filler, or generic CTA. "
            "Do not add disconnected hook or question patches after the script is reviewed.\n"
            + f"Editorial feedback: {review.get('issue_summary', '')} {review.get('rewrite_instruction', '')}\n"
            + "CURRENT DRAFT:\n" + json.dumps(script)
        )
    raise AssertionError("Unreachable script budget state")


def run_script(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[script] Generating script for {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    prompt_template = inject_strategy(open("prompts/script_prompt.txt").read(), "script")
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
        content_basis=research.get("content_basis", "emotional_observation"),
        content_format=research.get("content_format", "scenario"),
        emotional_trigger=research.get("emotional_trigger", ""),
        psych_concept=research.get("psych_concept", ""),
        core_claim=research.get("core_claim", ""),
        editorial_seed=research.get("editorial_seed", ""),
        only_soft_reset_line=research.get("only_soft_reset_line", ""),
        performance_insights=performance_insights,
        video_id=video_id,
        generated_at=now_iso(),
        target_words_min=config["script_min_words"],
        target_words_max=config["script_max_words"],
        hard_words_min=config.get("script_hard_min_words", max(1, config["script_min_words"] - 10)),
        hard_words_max=config.get("script_hard_max_words", config["script_max_words"] + 20),
    )

    script = _bounded_script_generation(prompt, research, config, run_dir)
    output_path = os.path.join(run_dir, "02_script.json")
    _log_final_state(script)
    save_json(script, output_path)
    print(f"[script] Done. Words: {script['word_count']}, validation: {script['validation']}")
    return script


def run_script_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[script][MOCK] Generating mock script for {video_id}")
    result = {
        "script_version": "1",
        "prompt_version": "soft-reset-script-v2.7",
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
        "tension": "That is why it still hurts. You are grieving a version that never arrived. You keep returning to moments that only existed in possibility.",
        "insight": "You miss the apology they almost gave. The effort they almost made. That was not love. That was hope with someone else's face on it.",
        "loopback": "Grieve the dream. Do not chase the person.",
        "cta": "Save this for when you start missing their potential.",
        "engagement_question": "Which hurts more: missing them, or missing who you imagined?",
        "like_cta": "Save this for when you start missing their potential.",
        "thumbnail_text": "YOU LOST THE DREAM",
        "word_count": 0,
        "estimated_duration_sec": 25,
        "validation": "passed",
        "generated_at": now_iso(),
    }
    result = _validate_script(result, config)
    output_path = os.path.join(run_dir, "02_script.json")
    save_json(result, output_path)
    print(f"[script][MOCK] Done.")
    return result
