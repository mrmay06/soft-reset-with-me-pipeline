from __future__ import annotations

import json
import os
from utils.ai_usage import measured_call


try:
    from google import genai as _genai
    from google.genai import types as _genai_types
except ImportError:
    _genai = None


def _api_key() -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return api_key


def generate_json(prompt: str, model: str) -> dict | list:
    api_key = _api_key()

    if _genai is not None:
        client = _genai.Client(api_key=api_key)
        response = measured_call("google", model, "json", client.models.generate_content,
            model=model,
            contents=prompt,
            config=_genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return json.loads(response.text)

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = measured_call("google", model, "json", client.generate_content,
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def generate_json_with_images(prompt: str, images: list[bytes], model: str) -> dict | list:
    """JSON response for a prompt plus JPEG frames."""
    api_key = _api_key()

    if _genai is not None:
        # Bounded so one stuck review cannot hold a whole production run.
        client = _genai.Client(api_key=api_key, http_options=_genai_types.HttpOptions(timeout=90_000))
        parts = [_genai_types.Part.from_bytes(data=image, mime_type="image/jpeg") for image in images]
        response = measured_call("google", model, "json_vision", client.models.generate_content,
            model=model,
            contents=[*parts, prompt],
            config=_genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return json.loads(response.text)

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = measured_call("google", model, "json_vision", client.generate_content,
        [*({"mime_type": "image/jpeg", "data": image} for image in images), prompt],
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def generate_text(prompt: str, model: str) -> str:
    api_key = _api_key()

    if _genai is not None:
        client = _genai.Client(api_key=api_key)
        response = measured_call("google", model, "text", client.models.generate_content, model=model, contents=prompt)
        return (response.text or "").strip()

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    response = measured_call("google", model, "text", genai.GenerativeModel(model).generate_content, prompt)
    return (response.text or "").strip()
