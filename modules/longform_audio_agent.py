from __future__ import annotations

import os

from utils.helpers import load_json, save_json, now_iso
from modules.tts import _call_gemini_tts, _generate_mock_mp3, _validate_audio


def _spoken_text(script: dict) -> str:
    return " ".join(ch.get("voiceover", "") for ch in script.get("chapters", [])).strip()


def _build_longform_tts_input(script: dict) -> str:
    style = (
        "Warm, calm, intimate long-form essay narration. The honest friend who's been through it. "
        "Speak steadily, not rushed. Keep sentence gaps natural but not slow. "
        "Never sound clinical, robotic, motivational, or dramatic.\n\n"
    )
    text = _spoken_text(script).replace("—", ",").replace("--", ",")
    return style + text


def run_longform_audio(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_audio] Generating voiceover for {video_id}")
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    output_path = os.path.join(run_dir, "04_longform_voice.mp3")
    _call_gemini_tts(_build_longform_tts_input(script), config, output_path)
    validation = _validate_audio(output_path, {
        **config,
        "audio_min_duration_sec": config.get("longform_target_min_sec", 300),
        "audio_max_duration_sec": config.get("longform_target_max_sec", 420),
    })
    meta = {
        "video_id": video_id,
        "voice": config["tts_voice"],
        "model": config["tts_model"],
        "duration_sec": validation["duration_sec"],
        "validation": validation["validation"],
        "generated_at": now_iso(),
    }
    if "warning" in validation:
        meta["warning"] = validation["warning"]
    save_json(meta, os.path.join(run_dir, "04_longform_voice_meta.json"))
    print(f"[longform_audio] Done. Duration: {meta['duration_sec']}s")
    return meta


def run_longform_audio_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_audio][MOCK] Generating mock long-form audio")
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    duration_sec = max(
        float(config.get("longform_target_min_sec", 300)),
        round(float(script.get("word_count", 780)) / 155 * 60, 1),
    )
    output_path = os.path.join(run_dir, "04_longform_voice.mp3")
    _generate_mock_mp3(output_path, duration_sec=duration_sec)
    meta = {
        "video_id": video_id,
        "voice": "mock_sine",
        "model": "mock",
        "duration_sec": duration_sec,
        "validation": "passed",
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "04_longform_voice_meta.json"))
    print(f"[longform_audio][MOCK] Done. Duration: {duration_sec}s")
    return meta
