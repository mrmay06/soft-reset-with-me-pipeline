"""Small compatibility helpers for Claude script and review requests."""


def request_options(model: str) -> dict:
    if model == "claude-sonnet-5-5":
        # Pass through older SDKs without depending on their thinking enums.
        return {"extra_body": {"thinking": {"type": "between_tools"},
                               "output_config": {"effort": "medium"}}}
    return {}


def response_text(message) -> str:
    if getattr(message, "stop_reason", None) == "max_tokens":
        raise ValueError("Claude output truncated before script/review completed")
    text = "".join(block.text for block in message.content
                   if getattr(block, "type", "text") == "text"
                   and isinstance(getattr(block, "text", None), str)).strip()
    if not text:
        raise ValueError("Claude returned no text for script/review")
    return text
