import os

from utils.helpers import load_json, save_json, now_iso
from utils.gemini_client import generate_json
from utils.retry import retry
from utils.youtube_tags import ensure_required_tags, sanitize_youtube_tags


@retry(max_attempts=2, wait_seconds=10, exceptions=(Exception,))
def _call_gemini_metadata(prompt: str, model: str) -> dict:
    result = generate_json(prompt, model)
    if not isinstance(result, dict):
        raise ValueError("Metadata model returned non-object JSON")
    return result


def _validate_metadata(metadata: dict, config: dict) -> dict:
    errors = []

    if len(metadata["title"]) > config["max_title_chars"]:
        metadata["title"] = metadata["title"][:config["max_title_chars"]]
        errors.append("title_truncated")

    if len(metadata["title"]) < 20:
        errors.append("title_too_short")

    original_tags = list(metadata["tags"])
    tag_count = len(original_tags)
    expected = config.get("tags_count", 27)
    if tag_count < 10:
        errors.append(f"tags_too_few: {tag_count}")
        if tag_count < 3:
            raise ValueError(f"Too few tags ({tag_count}) — metadata needs regeneration")
    if tag_count > expected + 2:
        metadata["tags"] = original_tags[:expected]
        errors.append("tags_truncated")

    before_sanitize = metadata["tags"]
    metadata["tags"] = sanitize_youtube_tags(
        ensure_required_tags(metadata["tags"]),
        config.get("youtube_tags_total_chars", 450),
    )
    if metadata["tags"] != before_sanitize:
        errors.append("tags_sanitized")

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
