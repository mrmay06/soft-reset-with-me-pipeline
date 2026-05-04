from __future__ import annotations

import json
import os


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
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=_genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return json.loads(response.text)

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel(model)
    response = client.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"},
    )
    return json.loads(response.text)


def generate_text(prompt: str, model: str) -> str:
    api_key = _api_key()

    if _genai is not None:
        client = _genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        return (response.text or "").strip()

    import google.generativeai as genai
    genai.configure(api_key=api_key)
    response = genai.GenerativeModel(model).generate_content(prompt)
    return (response.text or "").strip()
