from __future__ import annotations

import json
import hashlib
import os
import time

from utils.helpers import load_json, save_json, now_iso
from utils.ai_usage import measured_call


AUDIT_FILE = "09_video_audit.json"
AUDIT_VERSION = 2
BLOCKING_SEVERITIES = {"high", "critical"}


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


def _video_fingerprint(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as video:
        for chunk in iter(lambda: video.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def longform_audit_is_current(run_dir: str) -> bool:
    try:
        audit = load_json(os.path.join(run_dir, AUDIT_FILE))
        return (audit.get("status") == "ok" and audit.get("track") == "longform"
                and audit.get("audit_version") == AUDIT_VERSION
                and audit.get("render_sha256") == _video_fingerprint(os.path.join(run_dir, "06_longform_video.mp4")))
    except (OSError, ValueError, AttributeError):
        return False


def enforce_longform_visual_gate(run_dir: str, config: dict):
    if not config.get("public_release_enabled", False):
        return
    if not config.get("video_audit_enabled", True):
        raise RuntimeError("Public long-form release requires video_audit_enabled=true")
    if not longform_audit_is_current(run_dir):
        raise RuntimeError("Long-form video audit is missing, unavailable, or stale; recheck the current render")
    render = load_json(os.path.join(run_dir, "06_longform_render_meta.json"))
    valid_ids = {int(asset["beat_id"]) for asset in render.get("visual_assets", [])}
    if not valid_ids:
        raise RuntimeError("Long-form video audit requires a visual beat map")
    blockers = public_release_blockers(load_json(os.path.join(run_dir, AUDIT_FILE)), valid_ids)
    if blockers:
        raise RuntimeError(f"Long-form video audit blocked public upload: {blockers}")


def _longform_context(video_id: str, run_dir: str, config: dict) -> dict:
    from modules.longform_video_assembler import _build_visual_beats
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    render = load_json(os.path.join(run_dir, "06_longform_render_meta.json"))
    beats = {int(beat["id"]): beat for beat in _build_visual_beats(script, config)}
    scene_map = []
    elapsed = 0.0
    for asset in render.get("visual_assets", []):
        beat_id = int(asset["beat_id"])
        beat = beats[beat_id]
        duration = float(asset["duration_sec"])
        scene_map.append({"scene_id": beat_id, "start_sec": round(elapsed, 3),
                          "end_sec": round(elapsed + duration, 3),
                          "covers_dialogue": beat["voiceover"], "selected_clip": asset})
        elapsed += duration
    return {"video_id": video_id, "track": "longform", "scene_map": scene_map,
            "metadata": load_json(os.path.join(run_dir, "03_longform_metadata.json")),
            "end_hold_sec": render.get("end_hold_sec", 2.0)}


def _prompt(context: dict) -> str:
    format_name = "long-form video" if context.get("track") == "longform" else "Short"
    return (
        "You are Channel Strategist's video-audit specialist for Soft Reset With Me.\n"
        f"Watch the attached finished {format_name}. Do not judge topic performance from analytics; focus on video-specific causes "
        "that YouTube Analytics cannot show.\n\n"
        "Return ONLY valid JSON with this schema:\n"
        "{\n"
        '  "audit_version": 2,\n'
        '  "first_2_seconds": {"score": 0-10, "notes": "..."},\n'
        '  "hook_title_alignment": {"score": 0-10, "notes": "..."},\n'
        '  "caption_pacing": {"score": 0-10, "notes": "..."},\n'
        '  "visual_specificity": {"score": 0-10, "notes": "..."},\n'
        '  "emotional_tone": {"score": 0-10, "notes": "..."},\n'
        '  "audio_mix": {"score": 0-10, "notes": "..."},\n'
        '  "blocking_visual_mismatches": [{"scene_id": 1, "timestamp": "00:00-00:03", "narration": "...", "observed_visual": "...", "severity": "high|critical", "confidence": "high", "reason": "..."}],\n'
        '  "likely_dropoff_causes": ["..."],\n'
        '  "underrated_strengths": ["..."],\n'
        '  "repeat_next": ["..."],\n'
        '  "reduce_next": ["..."],\n'
        '  "tag_suggestions": {"hook_type": "...", "thumbnail_type": "...", "visual_style_mix": "...", "narrative_format": "...", "character_used": "..."},\n'
        '  "summary": "one concise paragraph",\n'
        '  "confidence": "low|medium|high"\n'
        "}\n\n"
        "A blocking visual mismatch must reverse or materially undermine the narration. "
        "Generic but emotionally compatible footage is not blocking. Include only high-confidence "
        "high/critical mismatches, and use scene_id values from SCENE MAP. Return an empty list when none exist.\n\n"
        "Different people and locations across clips are allowed. Do not infer that every clip depicts the same person. "
        "An intentional final narration-free hold is not a broken ending; music may continue through it.\n\n"
        "Pipeline context:\n"
        f"{json.dumps(context, indent=2) if context.get('track') == 'longform' else json.dumps(context, indent=2)[:12000]}"
    )


def public_release_blockers(audit: dict, valid_scene_ids: set[int]) -> list[dict]:
    """Validate a public-release audit and return its actionable contradictions."""
    if not isinstance(audit, dict) or audit.get("status") != "ok":
        status = audit.get("status", "invalid") if isinstance(audit, dict) else "invalid"
        raise RuntimeError(f"Video audit is not usable for public release (status={status})")
    if int(audit.get("audit_version", 0) or 0) < AUDIT_VERSION:
        raise RuntimeError("Video audit uses an obsolete schema; rerun the audit before public release")
    raw = audit.get("blocking_visual_mismatches")
    if not isinstance(raw, list):
        raise RuntimeError("Video audit is missing blocking_visual_mismatches")

    blockers: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RuntimeError("Video audit returned a malformed visual mismatch")
        try:
            scene_id = int(item.get("scene_id"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Video audit returned a mismatch without a valid scene_id") from exc
        severity = str(item.get("severity", "")).lower()
        confidence = str(item.get("confidence", "")).lower()
        if scene_id not in valid_scene_ids:
            raise RuntimeError(f"Video audit referenced unknown scene_id={scene_id}")
        if severity not in BLOCKING_SEVERITIES or confidence != "high":
            raise RuntimeError(
                "blocking_visual_mismatches may contain only high-confidence high/critical items"
            )
        normalized = dict(item)
        normalized.update({"scene_id": scene_id, "severity": severity, "confidence": confidence})
        blockers.append(normalized)
    return blockers


def _empty_result(video_id: str, status: str, reason: str) -> dict:
    return {
        "video_id": video_id,
        "status": status,
        "reason": reason,
        "generated_at": now_iso(),
    }


def run_video_audit(video_id: str, run_dir: str, config: dict) -> dict:
    """Watch the rendered video with Gemini and save creative observations."""
    output_path = os.path.join(run_dir, AUDIT_FILE)
    if not config.get("video_audit_enabled", True):
        result = _empty_result(video_id, "skipped", "video_audit_disabled")
        save_json(result, output_path)
        return result

    is_longform = config.get("longform_target_words_min") is not None
    video_path = os.path.join(run_dir, "06_longform_video.mp4" if is_longform else "06_final_video.mp4")
    if not os.path.exists(video_path):
        result = _empty_result(video_id, "skipped", "final_video_missing")
        save_json(result, output_path)
        return result

    try:
        render_hash = _video_fingerprint(video_path)
        genai = _get_gemini_client()
        uploaded = _upload_video(genai, video_path)
        model_name = config.get("video_audit_model") or config.get("weekly_analysis_model") or config.get("metadata_model", "gemini-3.8-flash")
        model = genai.GenerativeModel(model_name)
        context = {
            "video_id": video_id,
            "scene_map": [
                {
                    "scene_id": int(scene.get("id")),
                    "covers_dialogue": scene.get("covers_dialogue", ""),
                    "requested_query": scene.get("pexels_query", ""),
                    "selected_clip": (
                        _load_optional(os.path.join(run_dir, "03_asset_meta.json"), {})
                        .get("assets", {})
                        .get(f"scene_{scene.get('id')}", {})
                    ),
                }
                for scene in _load_optional(os.path.join(run_dir, "03b_scene_manifest.json"), {}).get("scenes", [])
            ],
            "research": _load_optional(os.path.join(run_dir, "01_research.json"), {}),
            "script": _load_optional(os.path.join(run_dir, "02_script.json"), {}),
            "metadata": _load_optional(os.path.join(run_dir, "07_metadata.json"), {}),
            "render_meta": _load_optional(os.path.join(run_dir, "06_render_meta.json"), {}),
            "creative_judge": _load_optional(os.path.join(run_dir, "10_judge_report.json"), {}),
        }
        if is_longform:
            context = _longform_context(video_id, run_dir, config)
        response = measured_call("google", model_name, "video_audit", model.generate_content, [
            _prompt(context),
            {"file_data": {"file_uri": uploaded.uri, "mime_type": "video/mp4"}},
        ])
        audit = _extract_json(response.text)
        if _video_fingerprint(video_path) != render_hash:
            raise RuntimeError("Rendered video changed during audit; recheck it")
        audit.update({
            "video_id": video_id,
            "status": "ok",
            "model": model_name,
            "generated_at": now_iso(),
            "track": "longform" if is_longform else "short",
            "render_sha256": render_hash,
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
        "audit_version": AUDIT_VERSION,
        "blocking_visual_mismatches": [],
        "summary": "Mock video audit skipped.",
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, AUDIT_FILE))
    return result
