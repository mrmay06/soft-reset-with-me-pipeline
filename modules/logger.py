import os
import re

from utils.helpers import load_json, save_json, now_iso

DEFAULT_MEMORY_FILE = "topic_memory.json"


def _load_memory(memory_file: str) -> list:
    if not os.path.exists(memory_file):
        return []
    return load_json(memory_file)


def _fingerprint(*parts: str) -> str:
    text = " ".join(str(part or "") for part in parts).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return " ".join(text.split())


def _write_memory(entry: dict, memory_file: str, max_entries: int = 30):
    memory = _load_memory(memory_file)
    youtube_video_id = entry.get("youtube_video_id")
    memory = [
        item for item in memory
        if item.get("video_id") != entry.get("video_id")
        and (
            not youtube_video_id
            or youtube_video_id == "MOCK_NOT_UPLOADED"
            or item.get("youtube_video_id") != youtube_video_id
        )
    ]
    memory.append(entry)
    if max_entries > 0:
        memory = memory[-max_entries:]
    save_json(memory, memory_file)


def run_logger(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[logger] Logging video {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    script = load_json(os.path.join(run_dir, "02_script.json"))
    metadata = load_json(os.path.join(run_dir, "07_metadata.json"))
    asset_meta = load_json(os.path.join(run_dir, "03_asset_meta.json"))
    upload_result = load_json(os.path.join(run_dir, "08_upload_meta.json"))
    memory_file = config.get("topic_memory_file", DEFAULT_MEMORY_FILE)
    max_entries = int(config.get("topic_memory_max_entries", 30))
    upload_status = (
        "generated_not_uploaded"
        if upload_result.get("youtube_video_id") == "MOCK_NOT_UPLOADED"
        else "uploaded"
    )

    entry = {
        "video_id": video_id,
        "published_date": now_iso()[:10],
        "status": upload_status,
        "topic": research["topic"],
        "category": research["category"],
        "angle_type": research.get("angle_type", ""),
        "total_score": research["total_score"],
        "source_name": research["source_name"],
        "content_format": research.get("content_format", ""),
        "emotional_trigger": research.get("emotional_trigger", ""),
        "psych_concept": research.get("psych_concept", ""),
        "core_claim": research.get("core_claim", ""),
        "editorial_seed": research.get("editorial_seed", ""),
        "only_soft_reset_line": script.get("only_soft_reset_line", research.get("only_soft_reset_line", "")),
        "editorial_quality": script.get("editorial_quality", ""),
        "hook": script.get("hook", ""),
        "hook_quality": script.get("hook_quality", ""),
        "word_count": script.get("word_count", 0),
        "estimated_duration_sec": script.get("estimated_duration_sec", 0),
        "thumbnail_text": script.get("thumbnail_text", ""),
        "content_fingerprint": _fingerprint(
            research.get("topic", ""),
            script.get("hook", ""),
            research.get("emotional_trigger", ""),
            research.get("psych_concept", ""),
            research.get("core_claim", ""),
            script.get("only_soft_reset_line", research.get("only_soft_reset_line", "")),
        ),
        "title": metadata["title"],
        "youtube_video_id": upload_result["youtube_video_id"],
        "youtube_url": upload_result["youtube_url"],
        "fallback_count": asset_meta["fallback_count"],
        "video_count": asset_meta.get("video_count", 0),
        "total_scenes": asset_meta.get("total_scenes", 0),
        "validation_warnings": metadata.get("validation_warnings", []),
    }

    try:
        _write_memory(entry, memory_file, max_entries)
        is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        if is_github_actions:
            print(f"[logger] Running in GitHub Actions — workflow will commit {memory_file}")
        else:
            print(f"[logger] Running locally — skipping git commit")
    except Exception as e:
        print(f"[logger] WARNING: Logger failed: {e}. Manual entry may be needed.")
        from utils.notify import send_failure_alert
        send_failure_alert(video_id, f"Logger failed: {e}", "")

    print(f"[logger] Done. Entry saved for {video_id}")
    return entry


def run_logger_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[logger][MOCK] Skipping persistent log (mock mode)")
    return {"video_id": video_id, "status": "mock_skipped"}
