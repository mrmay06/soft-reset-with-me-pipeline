"""Measured YouTube chapters for the long-form description.

Chapter starts come from the caption word timings, never from the model, and
the block is rebuilt from scratch on every run so a resume cannot duplicate it.
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from time import time_ns

from utils.caption_validation import file_hash
from utils.helpers import load_json, save_json, now_iso
from utils.script_contract import spoken_text_hash

MIN_CHAPTERS = 3          # YouTube ignores chapter lists shorter than this
MIN_CHAPTER_SEC = 10      # ...or with any chapter shorter than this
ALIGN_WINDOW = 8          # script tokens checked at the start of each chapter
ALIGN_MIN_MATCHES = 3
ALIGN_MAX_LEAD = 4        # unmatched tokens allowed before the first anchor
CHAPTERS_HEADER = "Chapters"
_TIMESTAMP_LINE = re.compile(r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}\b")


def _tokens(text: str) -> list[str]:
    # Drop apostrophes so "don't"/"dont" and "you're"/"youre" agree across whisper and the script.
    text = str(text or "").lower().replace("’", "'").replace("'", "")
    return re.findall(r"[a-z0-9]+", text)


def _parse_ass_time(value: str) -> float:
    hours, minutes, seconds = value.strip().split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def caption_word_timings(caption_path: str) -> list[dict]:
    """One {token, start, end} per spoken token; merged caption events share their onset."""
    words = []
    for line in Path(caption_path).read_text(encoding="utf-8").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start, end = _parse_ass_time(parts[1]), _parse_ass_time(parts[2])
        for token in _tokens(re.sub(r"\{[^}]*\}", "", parts[9])):
            words.append({"token": token, "start": start, "end": end})
    return words


def _chapter_token_spans(script: dict) -> tuple[list[str], list[tuple[int, int]]]:
    tokens, spans = [], []
    for chapter in script.get("chapters", []):
        start = len(tokens)
        tokens.extend(_tokens(chapter.get("voiceover", "")))
        spans.append((start, len(tokens)))
    return tokens, spans


def _aligned_start(mapping: dict[int, int], start: int, end: int) -> int | None:
    """Caption token index where a chapter starts, or None if the opening words don't line up."""
    window = range(start, min(end, start + ALIGN_WINDOW))
    matched = [i for i in window if i in mapping]
    if len(matched) < min(ALIGN_MIN_MATCHES, len(window)) or not matched:
        return None
    first, last = matched[0], matched[-1]
    lead = first - start
    if lead > ALIGN_MAX_LEAD:
        return None
    # Spurious matches on common words ("you", "the") scatter; real openings stay contiguous.
    if mapping[last] - mapping[first] > (last - first) + 3:
        return None
    previous = max((mapping[i] for i in mapping if i < start), default=-1)
    return max(previous + 1, mapping[first] - lead)


def chapter_start_times(script: dict, words: list[dict]) -> list[dict]:
    """Start time per script chapter, aligned to captions with a word-count fallback."""
    script_tokens, spans = _chapter_token_spans(script)
    caption_tokens = [item["token"] for item in words]
    mapping = {}
    if script_tokens and caption_tokens:
        matcher = SequenceMatcher(None, script_tokens, caption_tokens, autojunk=False)
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                mapping[block.a + offset] = block.b + offset

    results = []
    for index, (start, end) in enumerate(spans):
        if index == 0:
            results.append({"start_sec": 0.0, "method": "first_chapter"})
            continue
        caption_index = _aligned_start(mapping, start, end) if start < end else None
        if caption_index is not None and caption_index < len(words):
            results.append({"start_sec": words[caption_index]["start"], "method": "caption_alignment"})
        else:
            results.append({"start_sec": None, "method": "word_count_estimate"})

    # Interpolate unaligned chapters by word count between the nearest measured anchors.
    speech_end = max((item["end"] for item in words), default=0.0)
    anchors = [(spans[i][0], item["start_sec"]) for i, item in enumerate(results) if item["start_sec"] is not None]
    anchors.append((len(script_tokens), speech_end))
    for index, item in enumerate(results):
        if item["start_sec"] is not None:
            continue
        token = spans[index][0]
        before = max((a for a in anchors if a[0] <= token), key=lambda a: a[0])
        after = min((a for a in anchors if a[0] > token), key=lambda a: a[0], default=(len(script_tokens), speech_end))
        share = (token - before[0]) / max(1, after[0] - before[0])
        item["start_sec"] = before[1] + (after[1] - before[1]) * share
    return results


def format_timestamp(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def validate_chapters(chapters: list[dict], duration_sec: float) -> tuple[list[dict], str | None]:
    """Apply YouTube's rules on whole seconds, merging short chapters into a neighbour.

    Returns (chapters, None) when publishable, else ([], reason).
    """
    items = []
    for chapter in chapters:
        start = 0 if not items else int(math.floor(chapter["start_sec"]))
        if items and start <= items[-1]["start_sec"]:
            items[-1]["ids"] += chapter["ids"]
            continue
        items.append({**chapter, "ids": list(chapter["ids"]), "start_sec": start})
    end = int(math.floor(duration_sec))

    def lengths():
        return [(items[i + 1]["start_sec"] if i + 1 < len(items) else end) - item["start_sec"]
                for i, item in enumerate(items)]

    while len(items) > 1 and min(lengths()) < MIN_CHAPTER_SEC:
        current = lengths()
        index = current.index(min(current))
        if index == 0:
            absorb_next = True
        elif index == len(items) - 1:
            absorb_next = False
        else:
            absorb_next = current[index + 1] < current[index - 1]
        # Removing a boundary keeps the earlier chapter's title and start.
        keep, drop = (index, index + 1) if absorb_next else (index - 1, index)
        items[keep]["ids"] += items[drop]["ids"]
        del items[drop]

    if not items or items[0]["start_sec"] != 0:
        return [], "first chapter does not start at 0:00"
    if len(items) < MIN_CHAPTERS:
        return [], f"only {len(items)} chapter(s) of at least {MIN_CHAPTER_SEC}s"
    if min(lengths()) < MIN_CHAPTER_SEC:
        return [], f"a chapter is shorter than {MIN_CHAPTER_SEC}s"
    for item in items:
        item["timestamp"] = format_timestamp(item["start_sec"])
    return items, None


def chapter_block(chapters: list[dict]) -> str:
    return "\n".join([CHAPTERS_HEADER, *(f"{item['timestamp']} {item['title']}" for item in chapters)])


def _is_chapter_paragraph(paragraph: str) -> bool:
    lines = [line for line in paragraph.strip().splitlines() if line.strip()]
    if lines and lines[0].strip().rstrip(":").lower() in {"chapters", "timestamps"}:
        return len(lines) > 1 and all(_TIMESTAMP_LINE.match(line) for line in lines[1:])
    # Headerless lists must look like a chapter list, so a "2:00 am" opening line survives.
    return (len(lines) >= 2 and lines[0].strip().startswith("0:00")
            and all(_TIMESTAMP_LINE.match(line) for line in lines))


def strip_chapter_block(description: str) -> str:
    paragraphs = re.split(r"\n\s*\n", str(description or ""))
    kept = [paragraph for paragraph in paragraphs if not _is_chapter_paragraph(paragraph)]
    return description if len(kept) == len(paragraphs) else "\n\n".join(kept)


def insert_chapter_block(description: str, block: str) -> str:
    """Place the block after the opening paragraphs, before the subscribe line and hashtags."""
    paragraphs = re.split(r"\n\s*\n", strip_chapter_block(description).strip())
    position = next((i for i, p in enumerate(paragraphs)
                     if "@softresetwithme" in p.lower() or p.lstrip().lower().startswith("subscribe")), None)
    if position is None:
        position = next((i for i, p in enumerate(paragraphs) if p.lstrip().startswith("#")), len(paragraphs))
    return "\n\n".join(paragraphs[:position] + [block] + paragraphs[position:])


def _chapter_titles(metadata: dict, script: dict) -> dict[str, str]:
    titles = metadata.get("chapter_titles")
    if not isinstance(titles, list) or not titles:
        # Metadata written before chapter titles existed (resumed runs).
        from modules.longform_metadata_agent import fallback_chapter_titles
        titles = fallback_chapter_titles(script)
    return {str(item.get("id")): str(item.get("title", "")).strip() for item in titles if isinstance(item, dict)}


def build_longform_chapters(script: dict, metadata: dict, caption_path: str, duration_sec: float) -> dict:
    words = caption_word_timings(caption_path)
    if not words:
        return {"status": "omitted", "reason": "captions have no word timings", "chapters": []}
    titles = _chapter_titles(metadata, script)
    starts = chapter_start_times(script, words)
    raw = []
    for index, (chapter, timing) in enumerate(zip(script.get("chapters", []), starts)):
        chapter_id = str(chapter.get("id", index + 1))
        raw.append({"ids": [chapter_id], "title": titles.get(chapter_id) or f"Part {index + 1}",
                    "start_sec": timing["start_sec"], "method": timing["method"]})
    methods = {item["method"] for item in raw[1:]}
    method = ("caption_alignment" if methods <= {"caption_alignment"}
              else "word_count_estimate" if methods == {"word_count_estimate"} else "mixed")
    chapters, reason = validate_chapters(raw, duration_sec)
    record = {"status": "omitted" if reason else "published", "method": method,
              "measured_starts": [{"id": item["ids"][0], "start_sec": round(item["start_sec"], 2),
                                   "method": item["method"]} for item in raw],
              "chapters": [{"ids": item["ids"], "title": item["title"], "start_sec": item["start_sec"],
                            "timestamp": item["timestamp"], "method": item["method"]} for item in chapters]}
    if reason:
        record["reason"] = reason
    return record


def apply_longform_chapters(run_dir: str, config: dict) -> bool:
    """Rebuild the description's chapter block from current captions; return whether it changed.

    Runs on every pass (including resumes) before the creative judge, so judge,
    email, and upload all see the same description.
    """
    root = Path(run_dir)
    metadata_path = root / "03_longform_metadata.json"
    metadata = load_json(str(metadata_path))
    script = load_json(str(root / "02_longform_script.json"))
    caption_path = root / "04_longform_captions.ass"
    base = strip_chapter_block(metadata.get("description", ""))

    if not config.get("longform_chapters_enabled", True):
        record = {"status": "disabled", "chapters": []}
    elif not caption_path.is_file():
        record = {"status": "omitted", "reason": "captions missing", "chapters": []}
    else:
        duration = float(load_json(str(root / "04_longform_voice_meta.json"))["duration_sec"])
        record = build_longform_chapters(script, metadata, str(caption_path), duration)
        record["caption_sha256"] = file_hash(str(caption_path))
    record["script_sha256"] = spoken_text_hash(" ".join(ch.get("voiceover", "") for ch in script.get("chapters", [])))

    description = insert_chapter_block(base, chapter_block(record["chapters"])) if record["status"] == "published" else base
    previous = {k: v for k, v in (metadata.get("youtube_chapters") or {}).items() if k != "generated_at"}
    description_changed = description != metadata.get("description", "")
    if not description_changed and previous == record:
        return False

    if description_changed:
        # Same rule as packaging sync: a changed description needs a fresh judge pass.
        judge = root / "10_judge_report.json"
        if judge.exists():
            judge.replace(root / f"10_judge_report_before_chapter_sync_{time_ns()}.json")
    metadata["description"] = description
    metadata["youtube_chapters"] = {**record, "generated_at": now_iso()}
    save_json(metadata, str(metadata_path))
    if record["status"] == "published":
        print(f"[longform_chapters] {len(record['chapters'])} chapters published ({record['method']})")
    else:
        print(f"[longform_chapters] Chapters {record['status']}: {record.get('reason', 'config flag off')}")
    return description_changed
