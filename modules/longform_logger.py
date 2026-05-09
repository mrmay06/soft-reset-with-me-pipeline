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
    upload_meta = {}
    upload_path = os.path.join(run_dir, "09_longform_upload_meta.json")
    if os.path.exists(upload_path):
        upload_meta = load_json(upload_path)
    judge = {}
    judge_path = os.path.join(run_dir, "10_judge_report.json")
    if os.path.exists(judge_path):
        judge = load_json(judge_path)
    render_meta = {}
    render_path = os.path.join(run_dir, "06_longform_render_meta.json")
    if os.path.exists(render_path):
        render_meta = load_json(render_path)
    youtube_video_id = upload_meta.get("youtube_video_id", "")
    youtube_url = upload_meta.get("youtube_url", "")
    uploaded = bool(youtube_video_id and youtube_video_id != "MOCK_NOT_UPLOADED")
    entry = {
        "video_id": video_id,
        "published_date": now_iso()[:10],
        "status": "uploaded" if uploaded else ("rendered_not_uploaded" if render_meta else "brief_generated"),
        "topic": research.get("topic", ""),
        "working_title": research.get("working_title", ""),
        "content_pillar": research.get("content_pillar", ""),
        "category": research.get("content_pillar", ""),
        "angle_type": research.get("longform_format", ""),
        "longform_format": research.get("longform_format", ""),
        "core_claim": research.get("core_claim", ""),
        "editorial_seed": research.get("editorial_seed", ""),
        "only_soft_reset_line": script.get("only_soft_reset_line", ""),
        "word_count": script.get("word_count", 0),
        "estimated_duration_sec": script.get("estimated_duration_sec", 0),
        "argument_quality": script.get("argument_quality", ""),
        "final_duration_sec": render_meta.get("duration_sec", 0),
        "render_validation": render_meta.get("validation", ""),
        "title": metadata.get("title", ""),
        "primary_variant_id": metadata.get("primary_variant_id", ""),
        "title_variants": metadata.get("title_variants", []),
        "thumbnail_variants": metadata.get("thumbnail_variants", []),
        "thumbnail": "07_longform_thumbnail.png" if os.path.exists(os.path.join(run_dir, "07_longform_thumbnail.png")) else "",
        "youtube_video_id": youtube_video_id,
        "youtube_url": youtube_url,
        "privacy_status": upload_meta.get("privacy_status", config.get("privacy_status", "public")),
        "uploaded_at": upload_meta.get("uploaded_at", ""),
        "experiment_label": config.get("experiment_label", "baseline"),
        "experiment_id": config.get("experiment_id"),
        "strategy_version": config.get("strategy_version", ""),
        "judge_traits": judge.get("traits", {}),
        "judge_scores": judge.get("scores", {}),
        "judge_composite_score": judge.get("composite_score", 0),
        "strongest_element": judge.get("strongest_element", ""),
        "weakest_element": judge.get("weakest_element", ""),
        "only_soft_reset_score": judge.get("only_soft_reset_score", 0),
    }
    memory = [item for item in _load_memory(memory_file) if item.get("video_id") != video_id]
    memory.append(entry)
    max_entries = int(config.get("topic_memory_max_entries", 24))
    if max_entries > 0:
        memory = memory[-max_entries:]
    save_json(memory, memory_file)
    save_json(entry, os.path.join(run_dir, "11_longform_logger_meta.json"))
    print(f"[longform_logger] Done. Entry saved to {memory_file}")
    return entry


def run_longform_logger_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print("[longform_logger][MOCK] Skipping persistent log")
    result = {"video_id": video_id, "status": "mock_skipped"}
    save_json(result, os.path.join(run_dir, "11_longform_logger_meta.json"))
    return result
