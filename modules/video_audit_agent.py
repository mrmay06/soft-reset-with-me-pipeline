from __future__ import annotations

import json
import os
import time

from utils.helpers import load_json, save_json, now_iso


AUDIT_FILE = "09_video_audit.json"


def _load_optional(path: str, default):
    try:
        if os.path.exists(path):
            return load_json(path)
    except Exception:
        pass
    return default


def _get_gemini_client():
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    return genai


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:])
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def _upload_video(genai, video_path: str):
    uploaded = genai.upload_file(path=video_path, mime_type="video/mp4")
    for _ in range(30):
        uploaded = genai.get_file(uploaded.name)
        if uploaded.state.name == "ACTIVE":
            return uploaded
        if uploaded.state.name == "FAILED":
            raise RuntimeError("Gemini video file processing failed")
        time.sleep(3)
    raise RuntimeError("Gemini video file processing timed out")


def _prompt(context: dict) -> str:
    return (
        "You are Channel Strategist's video-audit specialist for Soft Reset With Me.\n"
        "Watch the attached finished Short. Do not judge topic performance from analytics; focus on video-specific causes "
        "that YouTube Analytics cannot show.\n\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "audit_version": 1,\n'
        '  "first_2_seconds": {"score": 0-10, "notes": "..."},\n'
        '  "hook_title_alignment": {"score": 0-10, "notes": "..."},\n'
        '  "caption_pacing": {"score": 0-10, "notes": "..."},\n'
        '  "visual_specificity": {"score": 0-10, "notes": "..."},\n'
        '  "emotional_tone": {"score": 0-10, "notes": "..."},\n'
        '  "audio_mix": {"score": 0-10, "notes": "..."},\n'
        '  "likely_dropoff_causes": ["..."],\n'
        '  "underrated_strengths": ["..."],\n'
        '  "repeat_next": ["..."],\n'
        '  "reduce_next": ["..."],\n'
        '  "tag_suggestions": {"hook_type": "...", "thumbnail_type": "...", "visual_style_mix": "...", "narrative_format": "...", "character_used": "..."},\n'
        '  "summary": "one concise paragraph",\n'
        '  "confidence": "low|medium|high"\n'
        "}\n\n"
        "Pipeline context:\n"
        f"{json.dumps(context, indent=2)[:6000]}"
    )


def _empty_result(video_id: str, status: str, reason: str) -> dict:
    return {
        "video_id": video_id,
        "status": status,
        "reason": reason,
        "generated_at": now_iso(),
    }


def run_video_audit(video_id: str, run_dir: str, config: dict) -> dict:
    """Watch the rendered Short with Gemini and save video-specific creative observations."""
    output_path = os.path.join(run_dir, AUDIT_FILE)
    if not config.get("video_audit_enabled", True):
        result = _empty_result(video_id, "skipped", "video_audit_disabled")
        save_json(result, output_path)
        return result

    video_path = os.path.join(run_dir, "06_final_video.mp4")
    if not os.path.exists(video_path):
        result = _empty_result(video_id, "skipped", "final_video_missing")
        save_json(result, output_path)
        return result

    try:
        genai = _get_gemini_client()
        uploaded = _upload_video(genai, video_path)
        model_name = config.get("video_audit_model") or config.get("weekly_analysis_model") or config.get("metadata_model", "gemini-2.5-flash")
        model = genai.GenerativeModel(model_name)
        context = {
            "video_id": video_id,
            "research": _load_optional(os.path.join(run_dir, "01_research.json"), {}),
            "script": _load_optional(os.path.join(run_dir, "02_script.json"), {}),
            "metadata": _load_optional(os.path.join(run_dir, "07_metadata.json"), {}),
            "render_meta": _load_optional(os.path.join(run_dir, "06_render_meta.json"), {}),
            "creative_judge": _load_optional(os.path.join(run_dir, "10_judge_report.json"), {}),
        }
        response = model.generate_content([
            _prompt(context),
            {"file_data": {"file_uri": uploaded.uri, "mime_type": "video/mp4"}},
        ])
        audit = _extract_json(response.text)
        audit.update({
            "video_id": video_id,
            "status": "ok",
            "model": model_name,
            "generated_at": now_iso(),
        })
        save_json(audit, output_path)
        print(f"[video_audit] Done. Saved {output_path}")
        return audit
    except Exception as exc:
        result = _empty_result(video_id, "soft_failed", str(exc))
        save_json(result, output_path)
        print(f"[video_audit] Soft-failed: {exc}")
        return result


def run_video_audit_mock(video_id: str, run_dir: str, config: dict) -> dict:
    result = {
        "video_id": video_id,
        "status": "mock",
        "audit_version": 1,
        "summary": "Mock video audit skipped.",
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, AUDIT_FILE))
    return result
