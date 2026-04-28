import os
import json

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry

try:
    import google.generativeai as genai
except ImportError:
    genai = None


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _call_gemini_metadata(prompt: str, model: str) -> dict:
    if genai is None:
        raise RuntimeError("google-generativeai not installed")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    return json.loads(response.text)


def _validate_metadata(metadata: dict, config: dict) -> dict:
    errors = []

    if len(metadata["title"]) > config["max_title_chars"]:
        metadata["title"] = metadata["title"][:config["max_title_chars"]]
        errors.append("title_truncated")

    if len(metadata["title"]) < 20:
        errors.append("title_too_short")

    tag_count = len(metadata["tags"])
    expected = config.get("tags_count", 27)
    if tag_count < 10:
        errors.append(f"tags_too_few: {tag_count}")
        if tag_count < 3:
            raise ValueError(f"Too few tags ({tag_count}) — metadata needs regeneration")
    if tag_count > expected + 2:
        metadata["tags"] = metadata["tags"][:expected]
        errors.append("tags_truncated")

    # Ensure "US" and "United States" are always present
    tags_lower = [t.lower() for t in metadata["tags"]]
    if "us" not in tags_lower:
        metadata["tags"].append("US")
    if "united states" not in tags_lower:
        metadata["tags"].append("United States")

    # Enforce 480 char total tag limit (YouTube hard limit)
    total_chars = sum(len(t) for t in metadata["tags"])
    if total_chars > 480:
        trimmed = []
        running = 0
        for tag in metadata["tags"]:
            if running + len(tag) <= 480:
                trimmed.append(tag)
                running += len(tag)
            else:
                break
        metadata["tags"] = trimmed
        errors.append(f"tags_char_limit_trimmed: was {total_chars} chars")

    if "not financial advice" not in metadata["description"].lower():
        metadata["description"] += "\nThis is educational content. Not financial advice."
        errors.append("disclaimer_added")

    metadata["validation_warnings"] = errors
    return metadata


def run_metadata(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[metadata] Generating metadata for {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    script = load_json(os.path.join(run_dir, "02_script.json"))

    prompt_template = open("prompts/metadata_prompt.txt").read()
    prompt = prompt_template.format(
        hook=script["hook"],
        topic=research["topic"],
        category=research["category"],
        angle=research.get("angle_type", research.get("angle", "")),
        source_fact=research["source_fact"],
    )

    raw = _call_gemini_metadata(prompt, config["metadata_model"])
    raw = _validate_metadata(raw, config)

    result = {
        "video_id": video_id,
        "title": raw["title"],
        "description": raw["description"],
        "tags": raw["tags"],
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "validation_warnings": raw.get("validation_warnings", []),
        "generated_at": now_iso(),
    }

    save_json(result, os.path.join(run_dir, "07_metadata.json"))
    print(f"[metadata] Done. Title: {result['title']}")
    return result


def run_metadata_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[metadata][MOCK] Generating mock metadata for {video_id}")
    result = {
        "video_id": video_id,
        "title": "The Credit Card Trick Banks Hope You Never Find",
        "description": (
            "Most people pay hundreds more in interest than they need to.\n"
            "Pay your credit card twice a month — before and after the statement date.\n"
            "Save this. Share it with someone still overpaying.\n"
            "#personalfinance #moneytips #creditcardhacks #debtfree #savemoney\n\n"
            "This is educational content. Not financial advice.\n\n"
            "#Shorts"
        ),
        "tags": [
            "personal finance tips", "credit card hacks", "how to pay less interest",
            "credit card debt", "money saving tips", "pay off debt faster",
            "financial tips for beginners", "credit card statement date trick",
            "reduce credit card interest", "debt free journey", "money tips us 2026",
            "personal finance 2026", "credit score tips", "budgeting tips",
            "financial freedom", "credit card billing cycle", "interest rate hacks",
            "credit card payment strategy", "avoid credit card interest",
            "money management tips", "finance shorts", "credit card tips",
            "save money fast", "debt payoff strategy", "financial advice shorts",
            "credit card tricks", "money hacks 2026",
        ],
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "validation_warnings": [],
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "07_metadata.json"))
    print(f"[metadata][MOCK] Done.")
    return result
