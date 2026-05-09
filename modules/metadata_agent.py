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

    metadata["title"] = metadata["title"].replace("#Shorts", "").replace("#SoftResetWithMe", "").strip()
    metadata["title"] = metadata["title"].rstrip(".")

    if len(metadata["title"]) > config["max_title_chars"]:
        metadata["title"] = metadata["title"][:config["max_title_chars"]].rstrip()
        errors.append("title_truncated")

    if len(metadata["title"]) < 20:
        errors.append("title_too_short")

    original_tags = list(metadata["tags"])
    tag_count = len(original_tags)
    expected = config.get("tags_count", 27)
    if tag_count < 8:
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
        config.get("youtube_tags_max_count", 15),
    )
    if metadata["tags"] != before_sanitize:
        errors.append("tags_sanitized")

    description = metadata["description"].strip()
    if "@softresetwithme" not in description.lower():
        description += "\n\nFollow for more — @SoftResetWithMe"
        errors.append("handle_added")
    if "#softresetwithme" not in description.lower():
        description += "\n\n#SoftResetWithMe #RelationshipAdvice #SelfWorth"
        errors.append("hashtags_added")
    metadata["description"] = description

    metadata["validation_warnings"] = errors
    return metadata


def _fallback_metadata(script: dict, research: dict) -> dict:
    topic = research.get("topic", "")
    category = research.get("category", "")
    title = script.get("hook") or topic or "Waiting on a maybe is choosing to wait"
    title = title.replace("#Shorts", "").replace("#SoftResetWithMe", "").strip().rstrip(".")
    if len(title) > 58:
        title = "Waiting on a 'maybe' is choosing to wait"

    pillar_tags = {
        "Self-Worth Shifts": ["#SelfWorth", "#Boundaries", "#MovingOn"],
        "Healing Arcs": ["#HealingJourney", "#BreakupAdvice", "#MovingOn"],
        "Relationship Patterns": ["#RelationshipAdvice", "#DatingAdvice", "#Situationship"],
        "Psychology Drops": ["#PsychologyFacts", "#SelfAwareness", "#EmotionalHealth"],
        "Conversation Truths": ["#RelationshipTips", "#CommunicationSkills", "#HonestTalk"],
        "Identity and Growth": ["#PersonalGrowth", "#SelfImprovement", "#GrowthMindset"],
    }
    hashtags = ["#SoftResetWithMe"] + pillar_tags.get(category, ["#RelationshipAdvice", "#SelfWorth", "#MovingOn"])
    hashtags = hashtags[:4]

    description = (
        f"{script.get('hook', title)}\n"
        "Save this for the moment uncertainty starts feeling like an answer.\n\n"
        "Follow for more — @SoftResetWithMe\n\n"
        + " ".join(hashtags)
    )

    tags = [
        "soft reset with me",
        "softreset",
        "relationship advice",
        "dating advice",
        "self worth",
        "setting boundaries",
        "situationship advice",
        "emotional healing",
        "moving on",
        "how to stop overthinking in relationships",
        "know your worth",
        "personal growth",
    ]
    return {"title": title, "description": description, "tags": tags, "validation_warnings": ["metadata_fallback"]}


def _inject_engagement_question(description: str, question: str) -> str:
    """Insert the script's engagement_question before the hashtag block."""
    if not question or question.lower() in description.lower():
        return description
    for marker in ("#Shorts", "#SoftResetWithMe", "#Relationship"):
        pos = description.find(marker)
        if pos > 0:
            return description[:pos].rstrip() + f"\n\n{question}\n\n" + description[pos:]
    return description + f"\n\n{question}"


def run_metadata(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[metadata] Generating metadata for {video_id}")

    research = load_json(os.path.join(run_dir, "01_research.json"))
    script = load_json(os.path.join(run_dir, "02_script.json"))

    from utils.strategy import inject_strategy
    prompt_template = inject_strategy(open("prompts/metadata_prompt.txt").read(), "metadata")
    prompt = prompt_template.format(
        hook=script["hook"],
        topic=research["topic"],
        category=research["category"],
        angle=research.get("angle_type", research.get("angle", "")),
        source_fact=research["source_fact"],
    )

    try:
        raw = _call_gemini_metadata(prompt, config["metadata_model"])
    except Exception as e:
        print(f"[metadata] Gemini failed ({e}) — using deterministic fallback")
        raw = _fallback_metadata(script, research)
    raw = _validate_metadata(raw, config)

    # Inject the script's engagement_question before hashtags — it's a free comment driver
    eq = str(script.get("engagement_question", "")).strip()
    raw["description"] = _inject_engagement_question(raw["description"], eq)

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
        "title": "You lost who you imagined",
        "description": (
            "Some heartbreak is grief for the version you invented.\n"
            "If this hit, share it with someone who needs to hear it.\n\n"
            "Follow for more — @SoftResetWithMe\n\n"
            "#SoftResetWithMe #HealingJourney #RelationshipAdvice #MovingOn"
        ),
        "tags": [
            "relationship advice",
            "emotional healing",
            "breakup advice",
            "moving on after breakup",
            "how to get over someone you love",
            "self worth",
            "personal growth",
            "healing journey",
            "soft reset with me",
            "softreset",
            "soft reset shorts",
        ],
        "category_id": config["youtube_category_id"],
        "privacy_status": config["privacy_status"],
        "validation_warnings": [],
        "generated_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "07_metadata.json"))
    print(f"[metadata][MOCK] Done.")
    return result
