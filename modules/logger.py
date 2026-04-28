import os
import subprocess

from utils.helpers import load_json, save_json, now_iso

MEMORY_FILE = "topic_memory.json"


def _load_memory() -> list:
    if not os.path.exists(MEMORY_FILE):
        return []
    return load_json(MEMORY_FILE)


def _write_memory(entry: dict):
    memory = _load_memory()
    memory.append(entry)
    save_json(memory, MEMORY_FILE)


def _commit_memory():
    try:
        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True, capture_output=True)
        subprocess.run(["git", "add", MEMORY_FILE], check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"], capture_output=True)
        if diff.returncode != 0:
            video_id = "unknown"
            subprocess.run(
                ["git", "commit", "-m", f"chore: log video {video_id}"],
                check=True, capture_output=True
            )
            subprocess.run(["git", "push"], check=True, capture_output=True)
            print(f"[logger] topic_memory.json committed and pushed")
        else:
            print(f"[logger] No changes to commit in topic_memory.json")
    except Exception as e:
        print(f"[logger] Git commit failed: {e} — skipping")


def run_logger(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[logger] Logging video {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    metadata = load_json(os.path.join(run_dir, "07_metadata.json"))
    asset_meta = load_json(os.path.join(run_dir, "03_asset_meta.json"))
    upload_result = load_json(os.path.join(run_dir, "08_upload_meta.json"))

    entry = {
        "video_id": video_id,
        "published_date": now_iso()[:10],
        "topic": research["topic"],
        "category": research["category"],
        "total_score": research["total_score"],
        "source_name": research["source_name"],
        "title": metadata["title"],
        "youtube_video_id": upload_result["youtube_video_id"],
        "youtube_url": upload_result["youtube_url"],
        "fallback_count": asset_meta["fallback_count"],
        "validation_warnings": metadata.get("validation_warnings", []),
    }

    try:
        _write_memory(entry)
        is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        if is_github_actions:
            _commit_memory()
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
