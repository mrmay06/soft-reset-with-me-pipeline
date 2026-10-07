"""Production caption evidence: real timestamps, transcript coverage, file identity."""
import hashlib
import math
import re
from difflib import SequenceMatcher
from pathlib import Path

from utils.helpers import load_json, save_json, now_iso
from utils.script_contract import spoken_text_hash


def file_hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


def merge_collapsed_words(words: list[dict]) -> list[dict]:
    """Keep ASR text at a shared measured onset, never invent a word duration."""
    merged = []
    pending = []
    for original in words:
        item = dict(original)
        start, end = float(item["start"]), float(item["end"])
        if pending:
            if start != float(pending[0]["start"]):
                raise RuntimeError("Collapsed caption word has no shared measured onset")
            item["word"] = " ".join(str(x["word"]) for x in pending) + " " + str(item["word"])
            pending = []
        if math.isfinite(start) and start >= 0 and end == start:
            pending.append(item)
        else:
            merged.append(item)
    if pending:
        raise RuntimeError("Trailing collapsed caption word has no measured interval")
    return merged


def validate_words(words: list[dict], transcript: str, duration: float) -> dict:
    if not words or not math.isfinite(duration) or duration <= 0:
        raise RuntimeError("Caption alignment requires real word timestamps and valid audio duration")
    previous_end = 0.0
    for item in words:
        start, end = float(item["start"]), float(item["end"])
        if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                or end <= start or start < previous_end - 0.02 or end > duration + 0.1):
            raise RuntimeError("Caption timestamps are invalid, overlapping, or outside the voice track")
        previous_end = end
    expected = _tokens(transcript)
    observed = _tokens(" ".join(str(item["word"]) for item in words))
    matches = sum(block.size for block in SequenceMatcher(None, expected, observed, autojunk=False).get_matching_blocks())
    coverage = matches / max(1, len(expected))
    precision = matches / max(1, len(observed))
    if not expected or coverage < 0.85 or precision < 0.85:
        raise RuntimeError(f"Caption transcript differs too much from script (coverage={coverage:.1%}, precision={precision:.1%})")
    return {"script_coverage": round(coverage, 4), "transcript_precision": round(precision, 4),
            "word_count": len(words), "timing_source": "audio_transcription"}


def caption_report_path(caption_path: str) -> str:
    return str(Path(caption_path).with_suffix(".validation.json"))


def save_caption_report(caption_path: str, audio_path: str, transcript: str, evidence: dict):
    save_json({**evidence, "status": "passed", "version": 1, "audio_sha256": file_hash(audio_path),
               "caption_sha256": file_hash(caption_path), "script_sha256": spoken_text_hash(transcript),
               "generated_at": now_iso()}, caption_report_path(caption_path))


def captions_are_current(caption_path: str, audio_path: str, transcript: str) -> bool:
    try:
        report = load_json(caption_report_path(caption_path))
        return (report.get("status") == "passed" and report.get("version") == 1
                and report.get("audio_sha256") == file_hash(audio_path)
                and report.get("caption_sha256") == file_hash(caption_path)
                and report.get("script_sha256") == spoken_text_hash(transcript))
    except (OSError, ValueError, AttributeError):
        return False
