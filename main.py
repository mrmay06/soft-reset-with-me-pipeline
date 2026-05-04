from __future__ import annotations
import os
import sys
import glob
import time
import warnings
import argparse
import traceback

# Suppress third-party Google SDK deprecation noise in CLI output.
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

from dotenv import load_dotenv
load_dotenv(override=True)

from utils.helpers import make_video_id, create_run_dir, load_config, load_json
from utils.notify import send_failure_alert, send_success_alert

from modules.research_agent import run_research, run_research_mock
from modules.script_agent import run_script, run_script_mock
from modules.tts import run_tts, run_tts_mock
from modules.visual_director import run_visual_director, run_visual_director_mock
from modules.image_gen import run_image_gen, run_image_gen_mock
from modules.caption_agent import run_captions, run_captions_mock
from modules.thumbnail_agent import run_thumbnail, run_thumbnail_mock
from modules.video_assembler import run_assembler, run_assembler_mock
from modules.metadata_agent import run_metadata, run_metadata_mock
from modules.uploader import run_upload, run_upload_mock
from modules.logger import run_logger, run_logger_mock


# ── Checkpoint helpers ──────────────────────────────────────────────────────

def _checkpoint(run_dir: str, *paths: str) -> bool:
    """Return True if ALL checkpoint files already exist (module already ran)."""
    return all(os.path.exists(os.path.join(run_dir, p)) for p in paths)


def _find_latest_run_dir() -> tuple[str, str] | None:
    """Find the most-recent incomplete run_dir. Returns (video_id, run_dir) or None."""
    terminal_checkpoints = ["06_final_video.mp4", "07_metadata.json", "08_upload_meta.json"]
    dirs = sorted(glob.glob("workspace/run_*"))
    for d in reversed(dirs):
        # Incomplete means any terminal stage has not finished yet.
        if not _checkpoint(d, *terminal_checkpoints):
            video_id = os.path.basename(d).replace("run_", "")
            return video_id, d
    return None


# ── Main ────────────────────────────────────────────────────────────────────

def main(mock: bool = False, resume_id: str | None = None, fresh: bool = False, skip_upload: bool = False):
    config = load_config()

    # ── Determine run_dir and video_id ──
    if resume_id:
        # Explicit resume of a specific run
        run_dir = f"workspace/run_{resume_id}"
        if not os.path.isdir(run_dir):
            print(f"[main] ERROR: run dir not found: {run_dir}")
            sys.exit(1)
        video_id = resume_id
        mode = "RESUME"
    elif not fresh and not mock and _find_latest_run_dir():
        # Auto-resume the latest incomplete run
        video_id, run_dir = _find_latest_run_dir()
        mode = "AUTO-RESUME"
    else:
        # Fresh start
        video_id = make_video_id()
        run_dir = create_run_dir(video_id)
        mode = "MOCK" if mock else "LIVE"

    print(f"\n{'='*50}")
    print(f" Soft Reset With Me Pipeline [{mode}]")
    print(f" Video ID: {video_id}")
    print(f" Run dir:  {run_dir}")
    print(f"{'='*50}\n")

    research_fn   = run_research_mock         if mock else run_research
    script_fn     = run_script_mock           if mock else run_script
    tts_fn        = run_tts_mock              if mock else run_tts
    director_fn   = run_visual_director_mock  if mock else run_visual_director
    image_fn      = run_image_gen_mock        if mock else run_image_gen
    captions_fn   = run_captions_mock         if mock else run_captions
    thumbnail_fn  = run_thumbnail_mock        if mock else run_thumbnail
    assembler_fn  = run_assembler_mock        if mock else run_assembler
    metadata_fn   = run_metadata_mock         if mock else run_metadata
    upload_fn     = run_upload_mock           if mock else run_upload
    logger_fn     = run_logger_mock           if mock else run_logger

    pipeline_start = time.time()
    timings = {}

    def _run(label: str, fn, *args, checkpoint_files: list = None):
        """Run a module, skip if checkpoint exists, record timing."""
        if checkpoint_files and _checkpoint(run_dir, *checkpoint_files):
            print(f"  {label:<30} SKIPPED (cached)\n")
            return
        t0 = time.time()
        fn(*args)
        elapsed = round(time.time() - t0, 1)
        timings[label.strip()] = elapsed
        print(f"  {label:<30} OK  ({elapsed}s)\n")

    try:
        _run("Module 1  — Research",        research_fn,  video_id, run_dir, config, checkpoint_files=["01_research.json"])
        _run("Module 2  — Script",           script_fn,    video_id, run_dir, config, checkpoint_files=["02_script.json"])
        _run("Module 3A — TTS",              tts_fn,       video_id, run_dir, config, checkpoint_files=["03_voice.mp3", "03_voice_meta.json"])
        _run("Module 3B — Visual Director",  director_fn,  video_id, run_dir, config, checkpoint_files=["03b_scene_manifest.json"])
        _run("Module 3C — Images",           image_fn,     video_id, run_dir, config, checkpoint_files=["03_asset_meta.json"])
        _run("Module 4  — Captions",         captions_fn,  video_id, run_dir, config, checkpoint_files=["04_captions.ass"])
        _run("Module 5  — Thumbnail",        thumbnail_fn, video_id, run_dir, config, checkpoint_files=["05_thumbnail.png"])
        _run("Module 6  — Video Assembly",   assembler_fn, video_id, run_dir, config, checkpoint_files=["06_final_video.mp4", "06_render_meta.json"])

        _run("Module 7  — Metadata",          metadata_fn,  video_id, run_dir, config, checkpoint_files=["07_metadata.json"])

        if skip_upload:
            run_upload_mock(video_id, run_dir, config)
            print(f"  {'Module 8  — Upload':<30} SKIPPED (--skip-upload)\n")
        elif mock:
            upload_fn(video_id, run_dir, config)
            print(f"  {'Module 8  — Upload':<30} SKIPPED (mock)\n")
        else:
            _run("Module 8  — Upload",            upload_fn,    video_id, run_dir, config, checkpoint_files=["08_upload_meta.json"])

        if skip_upload:
            if config.get("log_skip_upload_to_memory", True):
                t0 = time.time()
                logger_fn(video_id, run_dir, config)
                timings["Module 9  — Logger"] = round(time.time() - t0, 1)
                print(f"  {'Module 9  — Logger':<30} OK  (generated memory)\n")
            else:
                print(f"  {'Module 9  — Logger':<30} SKIPPED (--skip-upload)\n")
        else:
            t0 = time.time()
            logger_fn(video_id, run_dir, config)
            timings["Module 9  — Logger"] = round(time.time() - t0, 1)

        total = round(time.time() - pipeline_start, 1)
        print(f"{'='*50}")
        print(f" Pipeline complete!  Total: {total}s ({total/60:.1f} min)")
        print(f" Output: {run_dir}/06_final_video.mp4")
        print(f"{'='*50}")
        if timings:
            print(f"\n Timing breakdown:")
            for mod, secs in timings.items():
                print(f"   {mod:<30} {secs}s")
        print()

        # Success notification
        if not mock and not skip_upload:
            try:
                upload_meta = load_json(os.path.join(run_dir, "08_upload_meta.json"))
                send_success_alert(
                    video_id=video_id,
                    title=upload_meta.get("title", ""),
                    youtube_url=upload_meta.get("youtube_url", ""),
                    timings=timings,
                )
            except Exception:
                pass  # Never let notification failure crash the pipeline

    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n[main] Pipeline FAILED:\n{tb}")
        if not mock:
            send_failure_alert(video_id, str(e), tb)
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Soft Reset With Me Shorts Pipeline")
    parser.add_argument("--mock",   action="store_true", help="Run with mock data (no API calls)")
    parser.add_argument("--resume", metavar="VIDEO_ID",  help="Resume a specific run by video ID (e.g. 20260428_094245). If omitted, auto-resumes latest incomplete run.")
    parser.add_argument("--fresh",  action="store_true", help="Force a brand new run even if an incomplete run exists")
    parser.add_argument("--skip-upload", action="store_true", help="Generate all assets and metadata but do not upload or log to channel memory")
    args = parser.parse_args()

    main(mock=args.mock, resume_id=args.resume, fresh=args.fresh, skip_upload=args.skip_upload)
