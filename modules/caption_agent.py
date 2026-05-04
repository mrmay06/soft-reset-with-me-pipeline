import os
import re

from utils.helpers import load_json, now_iso
from utils.script_contract import build_spoken_script_text


def _clean_transcript(text: str) -> str:
    """
    Remove non-spoken tokens that break whisper alignment.
    Em-dashes, ellipses, standalone punctuation become spaces.
    """
    # Replace em-dash and double-dash with a space (pause, not spoken)
    text = text.replace("—", " ").replace("--", " ")
    # Replace ellipsis with space
    text = text.replace("…", " ").replace("...", " ")
    # Remove any remaining standalone punctuation tokens
    text = re.sub(r'\s([^a-zA-Z0-9\'\"]+)\s', ' ', text)
    # Collapse multiple spaces
    text = re.sub(r' +', ' ', text).strip()
    return text


def _build_transcript(script: dict) -> str:
    raw = build_spoken_script_text(script)
    return _clean_transcript(raw)


def _get_word_timestamps(audio_path: str, transcript: str) -> list:
    """
    Use faster-whisper directly for word-level timestamps — no VAD model needed.
    Falls back to evenly-spaced timestamps if transcription returns nothing.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper not installed — run: pip install faster-whisper")

    print("[captions] Loading faster-whisper base model…")
    model = WhisperModel("base", device="cpu", compute_type="int8")

    segments_gen, _ = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        beam_size=5,
    )

    # Collect word-level timestamps from faster-whisper
    # Use whisper's own words for both timing AND display — no index replacement.
    # Index-based replacement was causing drift whenever whisper tokenized
    # differently to the script (e.g. "Homeownership" vs "Home Ownership").
    raw_words = []
    for seg in segments_gen:
        for w in (seg.words or []):
            word = w.word.strip()
            # Skip pure punctuation tokens (em-dash, ellipsis, etc.)
            if not re.sub(r'[^a-zA-Z0-9\']', '', word):
                continue
            raw_words.append({
                "word":  word,
                "start": w.start,
                "end":   w.end,
            })

    if not raw_words:
        print("[captions] faster-whisper returned 0 words — using evenly-spaced fallback")
        return _evenly_spaced(transcript, _audio_duration(audio_path))

    return raw_words


def _audio_duration(audio_path: str) -> float:
    import subprocess, json as _json
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", audio_path],
        capture_output=True, text=True
    )
    return float(_json.loads(r.stdout)["format"]["duration"])


def _evenly_spaced(transcript: str, total_duration: float) -> list:
    words_list = transcript.split()
    if not words_list:
        return []
    dur = total_duration / len(words_list)
    return [
        {"word": w, "start": round(i * dur, 3), "end": round(i * dur + dur * 0.85, 3)}
        for i, w in enumerate(words_list)
    ]


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _write_ass_file(words: list, output_path: str):
    # PrimaryColour = white, SecondaryColour = white (no karaoke colour change),
    # Shadow = 2 for subtle depth, Outline = 0 (no border), FontSize = 95
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Montserrat ExtraBold,95,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,0,2,2,60,60,620,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    # 1 word at a time — each word is its own dialogue line
    for w in words:
        # Skip pure punctuation tokens (em-dash, ellipsis, etc.)
        clean = re.sub(r'[^a-zA-Z0-9\']', '', w["word"])
        if not clean:
            continue
        start_ts = _format_ass_time(w["start"])
        end_ts   = _format_ass_time(w["end"])
        display  = w["word"].capitalize()
        lines.append(f"Dialogue: 0,{start_ts},{end_ts},Default,,0,0,0,,{display}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))


def run_captions(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[captions] Generating captions for {video_id}")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    audio_path = os.path.join(run_dir, "03_voice.mp3")
    output_path = os.path.join(run_dir, "04_captions.ass")

    transcript = _build_transcript(script)
    words = _get_word_timestamps(audio_path, transcript)
    _write_ass_file(words, output_path)

    print(f"[captions] Done. {len(words)} words aligned.")
    return output_path


def _build_mock_words(transcript: str, total_duration: float) -> list:
    """Generate evenly-spaced word timestamps from transcript for mock mode."""
    words_list = transcript.split()
    if not words_list:
        return []
    duration_per_word = total_duration / len(words_list)
    words = []
    for i, word in enumerate(words_list):
        start = i * duration_per_word
        end = start + duration_per_word * 0.85
        words.append({"word": word, "start": round(start, 3), "end": round(end, 3)})
    return words


def run_captions_mock(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[captions][MOCK] Generating mock captions for {video_id}")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    voice_meta = load_json(os.path.join(run_dir, "03_voice_meta.json"))
    output_path = os.path.join(run_dir, "04_captions.ass")

    transcript = _build_transcript(script)
    words = _build_mock_words(transcript, voice_meta["duration_sec"])
    _write_ass_file(words, output_path)

    print(f"[captions][MOCK] Done. {len(words)} mock words.")
    return output_path
