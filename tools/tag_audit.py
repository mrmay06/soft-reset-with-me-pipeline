"""
tag_audit.py — Post-publish tag sanity check for Soft Reset With Me.

Compares the tags stored in each video's topic_memory entry against the topic
from its research JSON. Flags videos where tags look like they belong to a
different video (copy-over bug).

Usage:
    python tools/tag_audit.py
    python tools/tag_audit.py --fix

Requires: configured topic memory, workspace/ directory with run outputs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helpers import load_config, load_json

DEFAULT_TOPIC_MEMORY_FILE = "topic_memory_soft_reset.json"
WORKSPACE_DIR     = "workspace"


def _load_tags_from_workspace(video_id: str) -> list[str] | None:
    run_dir = os.path.join(WORKSPACE_DIR, f"run_{video_id}")
    meta_path = os.path.join(run_dir, "07_metadata.json")
    if not os.path.exists(meta_path):
        return None
    return load_json(meta_path).get("tags", [])


def _load_research_topic(video_id: str) -> str | None:
    run_dir = os.path.join(WORKSPACE_DIR, f"run_{video_id}")
    research_path = os.path.join(run_dir, "01_research.json")
    if not os.path.exists(research_path):
        return None
    return load_json(research_path).get("topic", "")


def _tags_look_mismatched(topic: str, tags: list[str]) -> bool:
    if not topic or not tags:
        return False
    topic_words = {w.lower() for w in topic.replace("-", " ").split() if len(w) > 3}
    tags_text = " ".join(tags).lower()
    matches = sum(1 for w in topic_words if w in tags_text)
    return matches < max(1, len(topic_words) // 4)


def audit(fix: bool = False, memory_file: str | None = None) -> list[dict]:
    memory_file = memory_file or load_config().get("topic_memory_file", DEFAULT_TOPIC_MEMORY_FILE)
    if not os.path.exists(memory_file):
        print(f"[tag_audit] {memory_file} not found.")
        return []

    memory = load_json(memory_file)
    if not isinstance(memory, list):
        return []

    published = [e for e in memory if e.get("youtube_video_id") and e["youtube_video_id"] != "MOCK_NOT_UPLOADED"]
    print(f"[tag_audit] Checking {len(published)} published videos\n")

    issues = []
    for entry in published:
        video_id  = entry.get("video_id", "")
        yt_id     = entry.get("youtube_video_id", "")
        mem_topic = entry.get("topic", "unknown")

        tags       = _load_tags_from_workspace(video_id)
        run_topic  = _load_research_topic(video_id)
        topic_to_check = run_topic or mem_topic

        if tags is None:
            print(f"  [SKIP] {video_id}: workspace output missing")
            continue

        if _tags_look_mismatched(topic_to_check, tags):
            issues.append({"video_id": video_id, "youtube_video_id": yt_id, "topic": topic_to_check, "tags_sample": tags[:5]})
            print(f"  [MISMATCH] {video_id} — yt:{yt_id}")
            print(f"    Topic: {topic_to_check}")
            print(f"    Tags:  {tags[:5]}")
            if fix:
                print(f"    ACTION: Update tags in YouTube Studio for {yt_id}")
            print()
        else:
            print(f"  [OK] {video_id} — {topic_to_check[:60]}")

    print(f"\n[tag_audit] {len(issues)} mismatches found out of {len(published)} published videos")
    if issues:
        with open("tag_audit_report.json", "w") as f:
            json.dump(issues, f, indent=2)
    return issues


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory", default=None, help="Topic memory JSON path")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()
    audit(fix=args.fix, memory_file=args.memory)
