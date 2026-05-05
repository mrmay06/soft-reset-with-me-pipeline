from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import warnings

from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=FutureWarning, module="google")
load_dotenv(override=True)

from utils.helpers import create_run_dir, load_config, make_video_id
from utils.notify import send_failure_alert
from modules.performance_agent import run_performance_sync, run_performance_sync_mock
from modules.longform_research_agent import run_longform_research, run_longform_research_mock
from modules.longform_script_agent import run_longform_script, run_longform_script_mock
from modules.longform_metadata_agent import run_longform_metadata, run_longform_metadata_mock
from modules.longform_audio_agent import run_longform_audio, run_longform_audio_mock
from modules.longform_caption_agent import run_longform_captions, run_longform_captions_mock
from modules.longform_video_assembler import run_longform_video, run_longform_video_mock
from modules.longform_thumbnail_agent import run_longform_thumbnail, run_longform_thumbnail_mock
from modules.longform_uploader import run_longform_upload, run_longform_upload_mock
from modules.longform_logger import run_longform_logger, run_longform_logger_mock


def _checkpoint(run_dir: str, *paths: str) -> bool:
    return all(os.path.exists(os.path.join(run_dir, p)) for p in paths)


def _apply_test_2min_overrides(config: dict) -> dict:
    config.update({
        "longform_duration_label": "about 2-minute test",
        "longform_target_min_sec": 95,
        "longform_target_max_sec": 125,
        "longform_validation_min_sec": 90,
        "longform_target_words_min": 220,
        "longform_target_words_max": 300,
        "longform_visual_max_beats": 42,
        "topic_memory_file": "topic_memory_soft_reset_long_test.json",
        "performance_memory_file": "performance_memory_soft_reset_long_test.json",
    })
    return config


def main(mock: bool = False, fresh: bool = False, test_2min: bool = False):
    config = load_config("config/longform_config.json")
    if test_2min:
        config = _apply_test_2min_overrides(config)
    video_id = "long_" + make_video_id()
    run_dir = create_run_dir(video_id)
    mode = "MOCK" if mock else "LIVE"

    print(f"\n{'=' * 58}")
    print(f" Soft Reset With Me Long-Form Pipeline [{mode}]")
    print(f" Video ID: {video_id}")
    print(f" Run dir:  {run_dir}")
    print(f"{'=' * 58}\n")

    performance_fn = run_performance_sync_mock if mock else run_performance_sync
    research_fn = run_longform_research_mock if mock else run_longform_research
    script_fn = run_longform_script_mock if mock else run_longform_script
    metadata_fn = run_longform_metadata_mock if mock else run_longform_metadata
    audio_fn = run_longform_audio_mock if mock else run_longform_audio
    captions_fn = run_longform_captions_mock if mock else run_longform_captions
    video_fn = run_longform_video_mock if mock else run_longform_video
    thumbnail_fn = run_longform_thumbnail_mock if mock else run_longform_thumbnail
    upload_fn = run_longform_upload_mock if mock else run_longform_upload
    logger_fn = run_longform_logger_mock if mock else run_longform_logger

    timings = {}
    pipeline_start = time.time()

    def _run(label: str, fn, *args, checkpoint_files: list[str] | None = None):
        if checkpoint_files and _checkpoint(run_dir, *checkpoint_files):
            print(f"  {label:<32} SKIPPED (cached)\n")
            return
        t0 = time.time()
        fn(*args)
        elapsed = round(time.time() - t0, 1)
        timings[label.strip()] = elapsed
        print(f"  {label:<32} OK  ({elapsed}s)\n")

    try:
        _run("Module 0 — Long Performance", performance_fn, video_id, run_dir, config, checkpoint_files=["00_performance_sync.json"])
        _run("Module 1 — Long Research", research_fn, video_id, run_dir, config, checkpoint_files=["01_longform_research.json"])
        _run("Module 2 — Long Script", script_fn, video_id, run_dir, config, checkpoint_files=["02_longform_script.json"])
        _run("Module 3 — Long Metadata", metadata_fn, video_id, run_dir, config, checkpoint_files=["03_longform_metadata.json"])
        _run("Module 4 — Long Audio", audio_fn, video_id, run_dir, config, checkpoint_files=["04_longform_voice.mp3", "04_longform_voice_meta.json"])
        _run("Module 5 — Long Captions", captions_fn, video_id, run_dir, config, checkpoint_files=["04_longform_captions.ass"])
        _run("Module 6 — Long Video", video_fn, video_id, run_dir, config, checkpoint_files=["06_longform_video.mp4", "06_longform_render_meta.json"])
        _run(
            "Module 7 — Long Thumbnail",
            thumbnail_fn,
            video_id,
            run_dir,
            config,
            checkpoint_files=[
                "07_longform_thumbnail.png",
                "07_longform_thumbnail_A.png",
                "07_longform_thumbnail_B.png",
                "07_longform_thumbnail_C.png",
                "07_longform_thumbnail_meta.json",
            ],
        )
        _run("Module 8 — Long Upload", upload_fn, video_id, run_dir, config, checkpoint_files=["09_longform_upload_meta.json"])
        _run("Module 9 — Long Logger", logger_fn, video_id, run_dir, config)

        total = round(time.time() - pipeline_start, 1)
        print(f"{'=' * 58}")
        print(f" Long-form video pipeline complete. Total: {total}s")
        print(f" Output: {run_dir}")
        print(f"{'=' * 58}")
        if timings:
            print("\n Timing breakdown:")
            for mod, secs in timings.items():
                print(f"   {mod:<32} {secs}s")
        print()
    except Exception as exc:
        tb = traceback.format_exc()
        print(f"\n[main_long] Pipeline FAILED:\n{tb}")
        if not mock:
            send_failure_alert(video_id, str(exc), tb)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Soft Reset With Me Long-Form Pipeline")
    parser.add_argument("--mock", action="store_true", help="Run with mock data")
    parser.add_argument("--fresh", action="store_true", help="Reserved for CLI symmetry with Shorts")
    parser.add_argument("--test-2min", action="store_true", help="Run a temporary 2-minute long-form test")
    args = parser.parse_args()
    main(mock=args.mock, fresh=args.fresh, test_2min=args.test_2min)
