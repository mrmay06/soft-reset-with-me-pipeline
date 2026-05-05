from __future__ import annotations

import os
import re

from utils.helpers import load_json
from utils.script_contract import word_count


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _clean_caption_text(text: str) -> str:
    text = str(text or "")
    text = text.replace("—", " ").replace("–", " ").replace("--", " ")
    text = text.replace("…", " ").replace("...", " ")
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _caption_events(script: dict, total_duration: float) -> list[tuple[float, float, str]]:
    chapters = script.get("chapters", [])
    total_words = max(1, sum(word_count(ch.get("voiceover", "")) for ch in chapters))
    cursor = 0.0
    events = []
    for chapter in chapters:
        text = str(chapter.get("voiceover", "")).strip()
        chapter_words = max(1, word_count(text))
        chapter_duration = total_duration * chapter_words / total_words
        sentences = _split_sentences(text)
        sentence_words_total = max(1, sum(word_count(sentence) for sentence in sentences))
        for sentence in sentences:
            sentence_duration = chapter_duration * max(1, word_count(sentence)) / sentence_words_total
            words = sentence.split()
            phrase = []
            phrase_start = cursor
            per_word = sentence_duration / max(1, len(words))
            for idx, word in enumerate(words):
                phrase.append(word)
                if len(phrase) >= 5 or idx == len(words) - 1:
                    end = cursor + per_word * (idx + 1)
                    display = _clean_caption_text(" ".join(phrase))
                    events.append((phrase_start, min(end, total_duration), display))
                    phrase = []
                    phrase_start = end
            cursor += sentence_duration
    return events


def _words_from_audio(audio_path: str) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return []

    print("[longform_captions] Loading faster-whisper base model...")
    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        beam_size=5,
    )
    words = []
    for segment in segments:
        for item in segment.words or []:
            text = _clean_caption_text(item.word)
            if not re.sub(r"[^a-zA-Z0-9']", "", text):
                continue
            words.append({
                "word": text,
                "start": float(item.start),
                "end": float(item.end),
            })
    return words


def _caption_events_from_words(words: list[dict], words_per_phrase: int) -> list[tuple[float, float, str]]:
    events = []
    phrase = []
    phrase_start = 0.0
    previous_end = 0.0
    for item in words:
        if phrase and item["start"] - previous_end > 0.85:
            events.append((phrase_start, previous_end, _clean_caption_text(" ".join(phrase))))
            phrase = []
        if not phrase:
            phrase_start = item["start"]
        phrase.append(item["word"])
        if len(phrase) >= words_per_phrase:
            events.append((phrase_start, item["end"], _clean_caption_text(" ".join(phrase))))
            phrase = []
        previous_end = item["end"]
    if phrase and words:
        events.append((phrase_start, words[-1]["end"], _clean_caption_text(" ".join(phrase))))
    return events


def _write_ass(events: list[tuple[float, float, str]], output_path: str):
    # ASS colours are AABBGGRR. Font: #F5F0E8, border: #1C1C2B.
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter Bold,54,&H00E8F0F5,&H00E8F0F5,&H002B1C1C,&H96000000,0,0,0,0,100,100,0,0,1,3,1,2,250,250,92,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [
        f"Dialogue: 0,{_format_ass_time(start)},{_format_ass_time(max(start + 0.25, end))},Default,,0,0,0,,{text}"
        for start, end, text in events
        if text.strip()
    ]
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(lines))


def run_longform_captions(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[longform_captions] Generating captions for {video_id}")
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    voice_meta = load_json(os.path.join(run_dir, "04_longform_voice_meta.json"))
    audio_path = os.path.join(run_dir, "04_longform_voice.mp3")
    output_path = os.path.join(run_dir, "04_longform_captions.ass")
    words = _words_from_audio(audio_path)
    if words:
        words_per_phrase = int(config.get("longform_caption_words_per_phrase", 4))
        events = _caption_events_from_words(words, max(2, words_per_phrase))
        print(f"[longform_captions] Synced from audio. {len(words)} words aligned.")
    else:
        print("[longform_captions] Audio alignment unavailable; using script timing fallback")
        events = _caption_events(script, float(voice_meta["duration_sec"]))
    _write_ass(events, output_path)
    print(f"[longform_captions] Done. {len(events)} phrase captions.")
    return output_path


run_longform_captions_mock = run_longform_captions
