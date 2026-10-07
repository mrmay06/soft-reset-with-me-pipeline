"""Allowlisted API usage only; never serialize requests, responses, or errors."""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

from utils.helpers import now_iso

_lock = threading.Lock()
_path = None
_stage = "pipeline"


def configure_usage(run_dir: str):
    global _path, _stage
    _path = Path(run_dir) / "ai_usage.jsonl"
    _stage = "pipeline"


@contextmanager
def usage_stage(stage: str):
    global _stage
    previous = _stage
    _stage = stage
    try:
        yield
    finally:
        _stage = previous


def _value(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def _usage(response, provider):
    usage = _value(response, "usage" if provider == "anthropic" else "usage_metadata")
    fields = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens") if provider == "anthropic" else (
        "prompt_token_count", "candidates_token_count", "total_token_count", "thoughts_token_count", "cached_content_token_count"
    )
    return {name: value for name in fields
            if isinstance(value := _value(usage, name), int) and not isinstance(value, bool) and value >= 0}


def measured_call(provider: str, model_name: str, operation: str, call, *args, **kwargs):
    started = time.monotonic()
    record = {"provider": provider, "model": model_name, "stage": _stage,
              "operation": operation, "started_at": now_iso(), "usage": {}, "usage_status": "unavailable"}
    try:
        response = call(*args, **kwargs)
        record["status"] = "response_received"
        record["usage"] = _usage(response, provider)
        if record["usage"]:
            record["usage_status"] = "reported"
        return response
    except Exception as error:
        record["status"] = "api_failed"
        record["error_type"] = type(error).__name__
        raise
    finally:
        record["elapsed_sec"] = round(time.monotonic() - started, 3)
        if _path is not None:
            # Tracking must not cause another paid retry if the log cannot save.
            try:
                with _lock, _path.open("a", encoding="utf-8") as log:
                    log.write(json.dumps(record) + "\n")
            except OSError:
                print("[ai_usage] Usage record could not be saved")
