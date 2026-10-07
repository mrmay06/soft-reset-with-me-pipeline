"""Resume real media production for the approved test Short, never publish."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import shutil
import time
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from utils.ai_usage import configure_usage, usage_stage
from utils.helpers import save_json
from main import (
    _enforce_script_review_gate, _enforce_creative_judge_gate, _run_public_visual_gate,
    run_tts, run_visual_director, run_image_gen, run_captions, run_thumbnail,
    run_assembler, run_metadata, run_creative_judge, run_video_audit, repair_scene_clips,
)


def main():
    root = Path("output/script_test_20261007/short")
    video_id = "script_test_20261007_short"
    config = json.loads(Path("config/pipeline_config.json").read_text())
    config.update(clip_memory_file=str(root / "test_clip_memory.json"),
                  log_skip_upload_to_memory=False, privacy_status="private")
    memory = Path(config["clip_memory_file"])
    if not memory.exists():
        source = Path("clip_memory_soft_reset.json")
        if source.exists():
            shutil.copyfile(source, memory)
        else:
            save_json([], str(memory))
    configure_usage(str(root))
    _enforce_script_review_gate(str(root))
    stages = [
        ("voice", run_tts, ["03_voice.mp3", "03_voice_meta.json"]),
        ("clip_direction", run_visual_director, ["03b_scene_manifest.json"]),
        ("clip_selection", run_image_gen, ["03_asset_meta.json"]),
        ("captions", run_captions, ["04_captions.ass"]),
        ("thumbnail", run_thumbnail, ["05_thumbnail.png"]),
        ("render", run_assembler, ["06_final_video.mp4", "06_render_meta.json"]),
        ("metadata", run_metadata, ["07_metadata.json"]),
        ("creative_review", run_creative_judge, ["10_judge_report.json"]),
        ("video_review", run_video_audit, ["09_video_audit.json"]),
    ]
    report = {"test_scope": "real_media_pipeline_from_approved_script",
              "fresh_research_tested": False, "youtube_upload_tested": False,
              "emails_sent": False, "production_memory_updated": False, "stages": []}
    try:
        for label, call, files in stages:
            start = time.monotonic()
            if all((root / name).exists() for name in files):
                status = "cached"
            else:
                with usage_stage(label):
                    call(video_id, str(root), config)
                status = "completed"
            report["stages"].append({"stage": label, "status": status,
                                     "seconds": round(time.monotonic() - start, 1)})
            if label == "creative_review":
                _enforce_creative_judge_gate(str(root))
            print(f"[test] {label}: {status}", flush=True)
        with usage_stage("visual_gate"):
            _run_public_visual_gate(video_id, str(root), config, run_video_audit,
                repair_scene_clips, run_thumbnail, run_assembler, run_creative_judge)
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        print(f"[test] Failed: {type(error).__name__}: {error}", flush=True)
    finally:
        save_json(report, str(root / "end_to_end_test.json"))
    print(json.dumps(report), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
