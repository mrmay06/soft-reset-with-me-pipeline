"""Small, explicit paid smoke check; no uploads and no application retries."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from utils.ai_usage import configure_usage, measured_call
from utils.claude_response import request_options, response_text
from modules.tts import _call_gemini_tts


def main():
    load_dotenv(override=True)
    root = Path("output") / ("api_access_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"))
    root.mkdir(parents=True)
    configure_usage(str(root))
    short = json.loads(Path("config/pipeline_config.json").read_text())
    long = json.loads(Path("config/longform_config.json").read_text())
    results = []

    def check(name, model, operation):
        try:
            detail = operation()
            record = {"check": name, "model": model, "status": "passed", **detail}
        except Exception as error:
            record = {"check": name, "model": model, "status": "failed",
                      "error_type": type(error).__name__}
            code = getattr(error, "status_code", None) or getattr(error, "code", None)
            if isinstance(code, (str, int)):
                record["error_code"] = code
            # Our TTS adapter only includes the safe HTTP status in this error.
            if type(error) is RuntimeError and str(error).startswith("Gemini TTS request failed (HTTP "):
                record["error"] = str(error)
        results.append(record)
        print(json.dumps(record), flush=True)

    def claude():
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=45)
        message = measured_call("anthropic", short["script_model"], "access_check", client.messages.create,
            model=short["script_model"], max_tokens=256,
            messages=[{"role": "user", "content": 'Return only this JSON object: {"ok":true}'}],
            **request_options(short["script_model"]))
        value = json.loads(response_text(message))
        if value != {"ok": True}:
            raise ValueError("Unexpected JSON response")
        return {"json_valid": True, "returned_model": message.model}

    def gemini():
        from google import genai
        from google.genai import types
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY missing")
        client = genai.Client(api_key=key)
        response = measured_call("google", short["research_model"], "access_check", client.models.generate_content,
            model=short["research_model"], contents='Return only this JSON object: {"ok":true}',
            config=types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=1024,
                thinking_config=types.ThinkingConfig(thinking_level="low")))
        if json.loads(response.text) != {"ok": True}:
            raise ValueError("Unexpected JSON response")
        return {"json_valid": True}

    def narration(config, name):
        output = root / f"{name}.mp3"
        result = _call_gemini_tts.__wrapped__(
            "Warm, natural, steady narration.\n\nYou can care about someone and still need space.",
            {**config, "tts_speed": 1.0}, str(output))
        return {"voice": config["tts_voice"], "audio_file": str(output.resolve()),
                "sample_rate_hz": result["raw_sample_rate_hz"],
                "source_mime_type": result["source_mime_type"]}

    check("anthropic_json", short["script_model"], claude)
    check("gemini_json", short["research_model"], gemini)
    check("short_narration", short["tts_model"], lambda: narration(short, "aoede"))
    check("long_narration", long["tts_model"], lambda: narration(long, "puck"))
    (root / "access_results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Evidence: {root.resolve()}", flush=True)
    return 0 if all(row["status"] == "passed" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
