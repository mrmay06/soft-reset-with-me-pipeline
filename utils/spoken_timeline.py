"""Compact spoken timeline for topic memory: when each script sentence starts.

The weekly strategy job cannot read workspace/ (gitignored, short-lived), so the
logger stores this small timeline in topic memory. Retention cliffs found weeks
later can then be mapped back to the exact spoken line.
"""
from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher

from utils.script_contract import SPOKEN_SECTION_KEYS, normalize_script_contract

TIMELINE_VERSION = 1
MAX_LINE_CHARS = 140

_DIALOGUE = re.compile(r"^Dialogue:\s*\d+,(\d+):(\d{2}):(\d{2})\.(\d{2}),(\d+):(\d{2}):(\d{2})\.(\d{2}),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(.*)$")


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower().replace("’", "'").replace("'", ""))


def _seconds(h: str, m: str, s: str, cs: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100


def parse_ass_words(ass_path: str) -> list[dict]:
    """Read word timings back out of the one-word-per-line ASS caption file."""
    words = []
    with open(ass_path, encoding="utf-8") as f:
        for line in f:
            match = _DIALOGUE.match(line.strip())
            if not match:
                continue
            g = match.groups()
            words.append({"word": g[8], "start": _seconds(*g[0:4]), "end": _seconds(*g[4:8])})
    return words


def script_sentences(script: dict) -> list[tuple[str, str]]:
    """Split the spoken sections into (section, sentence) pairs in spoken order."""
    normalized = normalize_script_contract(dict(script))
    sentences = []
    for key in SPOKEN_SECTION_KEYS:
        text = " ".join(str(normalized.get(key, "") or "").split())
        for part in re.split(r"(?<=[.!?])\s+", text):
            if _tokens(part):
                sentences.append((key, part))
    return sentences


def _line(start: float, section: str, text: str) -> dict:
    if len(text) > MAX_LINE_CHARS:
        text = text[:MAX_LINE_CHARS - 3].rstrip() + "..."
    return {"start": round(start, 2), "section": section, "text": text}


def align_sentences(sentences: list[tuple[str, str]], words: list[dict]) -> list[dict]:
    """Give each script sentence the measured start of its first matched caption word."""
    expected, owner = [], []
    for index, (_, sentence) in enumerate(sentences):
        for token in _tokens(sentence):
            expected.append(token)
            owner.append(index)
    observed, observed_start = [], []
    for word in words:
        for token in _tokens(word.get("word", "")):
            observed.append(token)
            observed_start.append(float(word["start"]))

    first_start: dict[int, float] = {}
    # Matching blocks arrive in spoken order, so the first hit per sentence is its onset.
    matcher = SequenceMatcher(None, expected, observed, autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            first_start.setdefault(owner[block.a + offset], observed_start[block.b + offset])

    lines = []
    previous = 0.0
    for index, (section, sentence) in enumerate(sentences):
        # A sentence whisper missed entirely inherits the previous start rather than a guess.
        start = max(first_start.get(index, previous), previous)
        lines.append(_line(start, section, sentence))
        previous = start
    return lines


def estimate_sentences(sentences: list[tuple[str, str]], voice_duration: float) -> list[dict]:
    """Word-count proportional starts, used only when no caption timing exists."""
    counts = [len(_tokens(sentence)) for _, sentence in sentences]
    total = sum(counts) or 1
    lines, elapsed = [], 0
    for (section, sentence), count in zip(sentences, counts):
        lines.append(_line(voice_duration * elapsed / total, section, sentence))
        elapsed += count
    return lines


def _load(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_spoken_timeline(run_dir: str, script: dict) -> dict:
    """Timeline from a finished Short run dir; empty dict when nothing usable exists."""
    sentences = script_sentences(script)
    if not sentences:
        return {}
    render_meta = _load(os.path.join(run_dir, "06_render_meta.json"))
    voice_meta = _load(os.path.join(run_dir, "03_voice_meta.json"))
    voice_duration = float(render_meta.get("voice_duration_sec") or voice_meta.get("duration_sec") or 0)
    duration = float(render_meta.get("final_duration_sec") or voice_duration or script.get("estimated_duration_sec") or 0)

    ass_path = os.path.join(run_dir, "04_captions.ass")
    words = parse_ass_words(ass_path) if os.path.exists(ass_path) else []
    if words:
        lines = align_sentences(sentences, words)
        source = "captions"
        voice_end = max(float(w["end"]) for w in words)
    elif voice_duration > 0:
        lines = estimate_sentences(sentences, voice_duration)
        source = "estimated"
        voice_end = voice_duration
    else:
        return {}

    return {
        "version": TIMELINE_VERSION,
        "source": source,
        "duration_sec": round(duration, 2) if duration else None,
        "voice_end_sec": round(voice_end, 2),
        "lines": lines,
    }
