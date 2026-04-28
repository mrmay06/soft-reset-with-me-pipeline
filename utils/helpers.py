import os
import json
from datetime import datetime


def create_run_dir(video_id: str) -> str:
    run_dir = os.path.join("workspace", f"run_{video_id}")
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(os.path.join(run_dir, "03_images"), exist_ok=True)
    return run_dir


def load_config(config_path: str = "config/pipeline_config.json") -> dict:
    with open(config_path, "r") as f:
        return json.load(f)


def load_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


def save_json(data: dict, path: str):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def make_video_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d_%H%M%S")
