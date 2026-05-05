from __future__ import annotations

import os
import re

from utils.helpers import load_json
from utils.script_contract import word_count


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [part.strip() for part in parts if part.strip()]


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
                    display = " ".join(phrase).replace("{", "").replace("}", "")
                    events.append((phrase_start, min(end, total_duration), display))
                    phrase = []
                    phrase_start = end
            cursor += sentence_duration
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
    output_path = os.path.join(run_dir, "04_longform_captions.ass")
    events = _caption_events(script, float(voice_meta["duration_sec"]))
    _write_ass(events, output_path)
    print(f"[longform_captions] Done. {len(events)} phrase captions.")
    return output_path


run_longform_captions_mock = run_longform_captions
