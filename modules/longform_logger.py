from __future__ import annotations

import os

from utils.helpers import load_json, save_json, now_iso


def _load_memory(path: str) -> list:
    if not os.path.exists(path):
        return []
    data = load_json(path)
    return data if isinstance(data, list) else []


def run_longform_logger(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_logger] Logging long-form brief {video_id}")
    memory_file = config.get("topic_memory_file", "topic_memory_soft_reset_long.json")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    entry = {
        "video_id": video_id,
        "published_date": now_iso()[:10],
        "status": "brief_generated",
        "topic": research.get("topic", ""),
        "working_title": research.get("working_title", ""),
        "content_pillar": research.get("content_pillar", ""),
        "longform_format": research.get("longform_format", ""),
        "core_claim": research.get("core_claim", ""),
        "editorial_seed": research.get("editorial_seed", ""),
        "only_soft_reset_line": script.get("only_soft_reset_line", ""),
        "word_count": script.get("word_count", 0),
        "estimated_duration_sec": script.get("estimated_duration_sec", 0),
        "argument_quality": script.get("argument_quality", ""),
        "title": metadata.get("title", ""),
        "youtube_video_id": "",
        "youtube_url": "",
    }
    memory = [item for item in _load_memory(memory_file) if item.get("video_id") != video_id]
    memory.append(entry)
    max_entries = int(config.get("topic_memory_max_entries", 24))
    if max_entries > 0:
        memory = memory[-max_entries:]
    save_json(memory, memory_file)
    print(f"[longform_logger] Done. Entry saved to {memory_file}")
    return entry


def run_longform_logger_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print("[longform_logger][MOCK] Skipping persistent log")
    return {"video_id": video_id, "status": "mock_skipped"}
