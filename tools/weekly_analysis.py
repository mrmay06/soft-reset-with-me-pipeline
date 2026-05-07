"""
Weekly Analysis
===============
Reads the pre-processed comparison file, optionally loads video files
for top/bottom performers (Gemini video watching), then calls Gemini
to produce a proposed strategy verdict.

Writes:
  strategy/strategy_memory_proposed.json   — pending your review
  strategy/analysis_history/YYYY-WW_verdict.json — archived copy

Usage:
    python tools/weekly_analysis.py
    python tools/weekly_analysis.py --week 2026-W20
    python tools/weekly_analysis.py --skip-video-watch   # skip MP4 upload to Gemini
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

COMPARISONS_DIR = "strategy/comparisons"
ANALYSIS_HISTORY_DIR = "strategy/analysis_history"
PROPOSED_FILE = "strategy/strategy_memory_proposed.json"
STRATEGY_FILE = "strategy/strategy_memory.json"
BRAND_BIBLE_FILE = "strategy/brand_bible.json"
WORKSPACE_DIR = "workspace"

MAX_VIDEO_WATCH = 2  # top N and bottom N performers to watch


def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def _get_gemini_client():
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai not installed")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    return genai


def _find_video_file(video_id: str, youtube_video_id: str) -> str | None:
    """Find the local MP4 for a given video_id."""
    for pattern in [f"run_{video_id}", f"run_long_{video_id}"]:
        candidate = os.path.join(WORKSPACE_DIR, pattern)
        for fname in ["06_final_video.mp4", "06_longform_video.mp4"]:
            path = os.path.join(candidate, fname)
            if os.path.exists(path):
                return path
    # Try scanning all run dirs for a judge_report matching the youtube_video_id
    import glob
    for run_dir in glob.glob(os.path.join(WORKSPACE_DIR, "run_*")):
        judge_path = os.path.join(run_dir, "10_judge_report.json")
        if os.path.exists(judge_path):
            try:
                with open(judge_path) as f:
                    report = json.load(f)
                if report.get("youtube_video_id") == youtube_video_id:
                    for fname in ["06_final_video.mp4", "06_longform_video.mp4"]:
                        path = os.path.join(run_dir, fname)
                        if os.path.exists(path):
                            return path
            except Exception:
                pass
    return None


def _upload_video_to_gemini(genai, video_path: str, label: str) -> str | None:
    """Upload a video file to Gemini Files API. Returns file URI or None on failure."""
    try:
        print(f"  [analysis] Uploading {label} video to Gemini Files API...")
        file = genai.upload_file(path=video_path, mime_type="video/mp4")
        # Wait for processing
        import time
        for _ in range(30):
            file = genai.get_file(file.name)
            if file.state.name == "ACTIVE":
                print(f"  [analysis] {label} video ready: {file.uri}")
                return file.uri
            if file.state.name == "FAILED":
                print(f"  [analysis] {label} video processing failed")
                return None
            time.sleep(5)
        print(f"  [analysis] {label} video upload timed out")
        return None
    except Exception as e:
        print(f"  [analysis] Could not upload {label} video: {e}")
        return None


def _watch_videos(genai, comparison: dict, skip_video_watch: bool) -> str:
    """Upload top/bottom performer videos and get Gemini's observations."""
    if skip_video_watch:
        return "Video watching skipped (--skip-video-watch)."

    top = comparison.get("top_performers", [])[:MAX_VIDEO_WATCH]
    bottom = comparison.get("bottom_performers", [])[:MAX_VIDEO_WATCH]
    to_watch = [(v, "TOP") for v in top] + [(v, "BOTTOM") for v in bottom]

    if not to_watch:
        return "No top/bottom performers available for video watching."

    uploaded = []
    for entry, label in to_watch:
        vid_path = _find_video_file(entry.get("video_id", ""), entry.get("youtube_video_id", ""))
        if not vid_path:
            print(f"  [analysis] {label} video not found locally: {entry.get('title', '')[:40]}")
            continue
        uri = _upload_video_to_gemini(genai, vid_path, f"{label} — {entry.get('title', '')[:30]}")
        if uri:
            uploaded.append({"label": label, "uri": uri, "title": entry.get("title", ""), "traits": entry.get("traits", {}), "retention": entry.get("retention"), "ctr": entry.get("ctr")})

    if not uploaded:
        return "Could not watch any videos (files not found or upload failed)."

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        parts = []
        for v in uploaded:
            parts.append(f"\n{v['label']}: \"{v['title']}\" | retention={v['retention']}% | ctr={v['ctr']}%")
            parts.append({"file_data": {"file_uri": v["uri"], "mime_type": "video/mp4"}})

        observe_prompt = (
            "You are watching these YouTube videos for the channel Soft Reset With Me. "
            "For each video, briefly note: (1) thumbnail readability and concept sharpness, "
            "(2) opening scene effectiveness for the first 3 seconds, "
            "(3) caption pacing and visual-audio sync quality, "
            "(4) any obvious reason this video might perform above or below average. "
            "Keep observations factual and specific. Total response under 400 words."
        )
        response = model.generate_content([observe_prompt] + parts)
        return response.text.strip()
    except Exception as e:
        return f"Video watching failed: {e}"


def _call_gemini_analysis(genai, prompt: str, model_name: str = "gemini-2.0-flash") -> dict:
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    return json.loads(text)


def run_analysis(week_label: str | None = None, skip_video_watch: bool = False) -> str:
    if week_label is None:
        today = datetime.now(timezone.utc)
        iso = today.isocalendar()
        week_label = f"{iso[0]}-W{iso[1]:02d}"

    comparison_path = os.path.join(COMPARISONS_DIR, f"{week_label}_comparison.json")
    if not os.path.exists(comparison_path):
        raise FileNotFoundError(
            f"No comparison file for {week_label}. Run weekly_preprocess.py first."
        )

    print(f"\n[analysis] Week: {week_label}")

    comparison = _load_json(comparison_path)
    previous_strategy = _load_json(STRATEGY_FILE)
    brand_bible = _load_json(BRAND_BIBLE_FILE)

    genai = _get_gemini_client()

    print("[analysis] Watching top/bottom performer videos...")
    video_notes = _watch_videos(genai, comparison, skip_video_watch)
    print(f"[analysis] Video notes: {video_notes[:120]}...")

    prompt_template = open("prompts/weekly_analysis_prompt.txt").read()

    now_iso = datetime.now(timezone.utc).isoformat()
    window = comparison.get("analysis_window", f"up to {week_label}")
    prev_version = previous_strategy.get("version", "none")

    banned_phrases = ", ".join(brand_bible.get("banned_phrases_all_prompts", []))
    banned_thumb_words = ", ".join(brand_bible.get("banned_thumbnail_words", []))

    active_experiments = previous_strategy.get("experiment_slots", {})
    experiment_str = json.dumps(active_experiments, indent=2) if active_experiments else "None"

    prompt = prompt_template.format(
        banned_phrases=banned_phrases,
        banned_thumbnail_words=banned_thumb_words,
        previous_strategy=json.dumps(previous_strategy, indent=2)[:3000],
        comparison_data=json.dumps(comparison.get("comparisons_by_trait", {}), indent=2)[:6000],
        channel_trend=json.dumps(comparison.get("channel_trend_4weeks", {}), indent=2),
        top_performers=json.dumps(comparison.get("top_performers", []), indent=2),
        bottom_performers=json.dumps(comparison.get("bottom_performers", []), indent=2),
        video_analysis_notes=video_notes,
        active_experiments=experiment_str,
        week_label=week_label,
        generated_at=now_iso,
        analysis_window=window,
        previous_version=prev_version,
    )

    print("[analysis] Calling Gemini for strategy verdict...")
    try:
        verdict = _call_gemini_analysis(genai, prompt)
    except Exception as e:
        raise RuntimeError(f"Gemini analysis failed: {e}") from e

    # Ensure required top-level fields are present
    verdict.setdefault("version", week_label)
    verdict.setdefault("generated_at", now_iso)
    verdict["videos_analyzed"] = comparison.get("strategy_eligible_videos", 0)
    verdict["videos_excluded"] = comparison.get("total_videos", 0) - comparison.get("strategy_eligible_videos", 0)
    verdict["previous_version_reference"] = prev_version

    # Write proposed file
    with open(PROPOSED_FILE, "w") as f:
        json.dump(verdict, f, indent=2)

    # Archive
    os.makedirs(ANALYSIS_HISTORY_DIR, exist_ok=True)
    archive_path = os.path.join(ANALYSIS_HISTORY_DIR, f"{week_label}_verdict.json")
    shutil.copy(PROPOSED_FILE, archive_path)

    print(f"\n[analysis] Done.")
    print(f"  Proposed verdict: {PROPOSED_FILE}")
    print(f"  Archived at:      {archive_path}")
    print(f"\n  Channel health:   {verdict.get('channel_health_signal', 'N/A')}")
    print(f"  Brand check:      {verdict.get('brand_bible_override_check', 'N/A')}")
    print(f"\n  Proposed strategy is ready for weekly_strategy.py to auto-promote.")
    print(f"  Rollback remains available from {ANALYSIS_HISTORY_DIR}/.\n")

    return PROPOSED_FILE


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weekly Analysis")
    parser.add_argument("--week", default=None, help="ISO week label e.g. 2026-W20")
    parser.add_argument("--skip-video-watch", action="store_true", help="Skip Gemini video watching")
    args = parser.parse_args()
    run_analysis(week_label=args.week, skip_video_watch=args.skip_video_watch)
