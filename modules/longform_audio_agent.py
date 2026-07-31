from __future__ import annotations

import os
import subprocess

from utils.helpers import load_json, save_json, now_iso
from modules.tts import _call_gemini_tts, _generate_mock_mp3, _validate_audio


def _spoken_text(script: dict) -> str:
    return " ".join(ch.get("voiceover", "") for ch in script.get("chapters", [])).strip()


def _longform_tts_style() -> str:
    return (
        "Warm, calm, intimate long-form essay narration. The honest friend who's been through it. "
        "Speak steadily, not rushed. Keep sentence gaps natural but not slow. "
        "Never sound clinical, robotic, motivational, or dramatic. "
        "VOICE CONTINUITY LOCK: preserve exactly the same vocal identity, baseline pitch, timbre, "
        "accent, microphone distance, energy, and speaking rate from the first sentence to the last. "
        "Do not gradually deepen, brighten, distort, whisper, or become more theatrical.\n\n"
    )


def _build_longform_tts_input(script: dict) -> str:
    text = _spoken_text(script).replace("—", ",").replace("--", ",")
    return _longform_tts_style() + text


def _build_tts_chunks(script: dict, max_words: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_words = 0
    for chapter in script.get("chapters", []):
        text = str(chapter.get("voiceover", "")).strip().replace("—", ",").replace("--", ",")
        words = len(text.split())
        if current and current_words + words > max_words:
            chunks.append(" ".join(current))
            current, current_words = [], 0
        if text:
            current.append(text)
            current_words += words
    if current:
        chunks.append(" ".join(current))
    return chunks or [_spoken_text(script)]


def _concat_tts_chunks(paths: list[str], output_path: str, run_dir: str) -> None:
    list_path = os.path.join(run_dir, "04_longform_tts_concat.txt")
    with open(list_path, "w", encoding="utf-8") as handle:
        for path in paths:
            handle.write(f"file '{os.path.abspath(path)}'\n")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-acodec", "libmp3lame", "-q:a", "2", output_path,
        ],
        check=True,
        capture_output=True,
    )


def run_longform_audio(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_audio] Generating voiceover for {video_id}")
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    output_path = os.path.join(run_dir, "04_longform_voice.mp3")
    chunks = _build_tts_chunks(script, int(config.get("longform_tts_chunk_words", 220)))
    if len(chunks) == 1:
        _call_gemini_tts(_longform_tts_style() + chunks[0], config, output_path)
    else:
        chunks_dir = os.path.join(run_dir, "04_longform_tts_chunks")
        os.makedirs(chunks_dir, exist_ok=True)
        chunk_paths = []
        for index, text in enumerate(chunks, start=1):
            chunk_path = os.path.join(chunks_dir, f"chunk_{index:02d}.mp3")
            _call_gemini_tts(_longform_tts_style() + text, config, chunk_path)
            chunk_paths.append(chunk_path)
        _concat_tts_chunks(chunk_paths, output_path, run_dir)
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
        "tts_chunks": len(chunks),
        "continuity_lock": True,
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
