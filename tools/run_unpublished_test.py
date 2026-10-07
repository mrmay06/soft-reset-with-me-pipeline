"""Real fresh generation with upload/email disabled and isolated memory copies."""
from pathlib import Path
import argparse
from datetime import datetime
import shutil
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.helpers import load_config, save_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("format", choices=["short", "long"])
    parser.add_argument("--resume", help="Resume this tool's isolated unpublished run")
    parser.add_argument("--recheck-script", action="store_true", help="Revalidate saved Short after a hook-check fix")
    parser.add_argument("--rewrite-script", action="store_true", help="Correct a rejected saved Short using its editorial feedback")
    args = parser.parse_args()
    long = args.format == "long"
    if long:
        import main_long as pipeline
    else:
        import main as pipeline
    config = load_config("config/longform_config.json" if long else "config/pipeline_config.json")
    stamp = args.resume.removeprefix("long_") if args.resume else "test_" + datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    video_id = ("long_" if long else "") + stamp
    directory = ROOT / "workspace" / f"run_{video_id}"
    directory.mkdir(parents=True, exist_ok=bool(args.resume))
    if args.resume and not (directory / "test_scope.json").exists():
        raise RuntimeError("Only this tool's isolated unpublished runs may be resumed")
    for key, default in (
        ("topic_memory_file", "topic_memory_soft_reset.json"),
        ("performance_memory_file", "performance_memory_soft_reset.json"),
        ("longform_clip_memory_file" if long else "clip_memory_file",
         "clip_memory_soft_reset_long.json" if long else "clip_memory_soft_reset.json"),
    ):
        source = ROOT / config.get(key, default)
        target = directory / source.name
        if source.exists() and not target.exists():
            shutil.copyfile(source, target)
        config[key] = str(target)
    config["log_skip_upload_to_memory"] = False
    config["privacy_status"] = "private"
    save_json({"scope": "fresh_real_generation", "format": args.format,
               "youtube_upload_enabled": False, "email_enabled": False,
               "production_memory_updates_enabled": False}, str(directory / "test_scope.json"))

    def no_upload(identifier, run_dir, settings):
        save_json({"video_id": identifier, "youtube_video_id": "MOCK_NOT_UPLOADED",
                   "status": "test_not_uploaded", "privacy_status": "private"},
                  str(Path(run_dir) / "09_longform_upload_meta.json"))
        print("[test] Upload disabled: real video remains local", flush=True)

    print(f"[test] Fresh unpublished {args.format}: {directory}", flush=True)
    if args.rewrite_script:
        if long:
            raise RuntimeError("Saved-draft correction here is only supported for Shorts")
        from modules import script_agent
        from utils.helpers import load_json
        from utils.ai_usage import configure_usage, usage_stage
        saved = load_json(str(directory / "02_script.json"))
        feedback = saved.get("argument_review", {}).get("issue_summary", "")
        if not feedback:
            raise RuntimeError("No saved editorial feedback available")
        original_call = script_agent._call_script_model
        first = True

        def corrected_call(prompt, model):
            nonlocal first
            if first:
                prompt += "\n\nPrevious draft was rejected. Address this feedback in the new draft, not by adding disclaimers: " + feedback
                first = False
            return original_call(prompt, model)

        configure_usage(str(directory))
        with patch.object(script_agent, "_call_script_model", side_effect=corrected_call), usage_stage("corrected_script"):
            script_agent.run_script(video_id, str(directory), config)
    if args.recheck_script:
        if long:
            raise RuntimeError("Saved-hook recheck is only supported for Shorts")
        from utils.helpers import load_json
        from utils.ai_usage import configure_usage, usage_stage
        from modules.script_agent import _validate_script, _check_argument_coherence, _attach_argument_review
        script = load_json(str(directory / "02_script.json"))
        if script.get("validation_notes", "").split("bounded script correction budget exhausted: ")[-1] != "weak_hook":
            raise RuntimeError("Refusing to clear anything except the reproduced weak_hook false rejection")
        script["validation"] = "passed"
        script.pop("human_review_required", None)
        script = _validate_script(script, config)
        if script["validation"] != "passed" or script.get("hook_quality") != "strong":
            raise RuntimeError("Saved script still fails validation")
        configure_usage(str(directory))
        with usage_stage("saved_draft_editorial_review"):
            review = _check_argument_coherence(script, load_json(str(directory / "01_research.json")), config)
        script = _attach_argument_review(script, review)
        save_json(script, str(directory / "02_script.json"))
        if not review.get("passes"):
            raise RuntimeError("Saved draft failed editorial review; refusing media generation")
    with patch.object(pipeline, "load_config", return_value=config), \
         patch.object(pipeline, "make_video_id", return_value=stamp), \
         patch.object(pipeline, "send_failure_alert"):
        if long:
            with patch.object(pipeline, "check_youtube_refresh_token"), \
                 patch.object(pipeline, "send_longform_upload_confirmation"), \
                 patch.object(pipeline, "run_longform_upload", side_effect=no_upload):
                pipeline.main(fresh=not bool(args.resume), resume_id=args.resume)
        else:
            pipeline.main(fresh=not bool(args.resume), resume_id=args.resume, skip_upload=True)


if __name__ == "__main__":
    main()
