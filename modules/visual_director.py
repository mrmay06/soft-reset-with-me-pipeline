import os
import json
import warnings

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry

warnings.filterwarnings("ignore", category=FutureWarning, module="google")

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
except ImportError:
    _genai = None

try:
    import google.generativeai as _genai_old
except ImportError:
    _genai_old = None


# ── Prompt ───────────────────────────────────────────────────────────────────

DIRECTOR_PROMPT = """You are a visual director for a 30-60 second vertical finance YouTube Short (1080x1920).

Read this script as plain spoken dialogue — no section labels, just the words the narrator says:
"{raw_dialogue}"

Your job — decide where visual CUTS should happen based purely on what is being SAID:
- A single visual can hold across multiple sentences if the topic doesn't shift.
- Cut when the subject, emotion, location, or tone meaningfully changes.
- Do NOT cut on every sentence. Group related sentences together.

For each scene choose visual_type:
  "image" → AI-generated photo (specific objects described, data/numbers, reveals,
             concepts, close-up details, key moments that need a clear still)
  "video" → stock footage (human emotion, action, movement, scale, relatable scenes)

For IMAGE scenes write a detailed image_prompt (30+ words):
  - Specific subject + action + setting
  - Camera angle (overhead, eye-level, close-up, wide, etc.)
  - Lighting (golden hour, soft window light, dramatic spotlight, etc.)
  - Depth of field (shallow bokeh, sharp, cinematic)
  - Mood and colour grade
  - MUST end with: "photorealistic, professional photography, HD, no text overlays"
  - NEVER: illustrations, cartoons, 3D renders, digital art

For VIDEO scenes write pexels_query: 3-5 word search term only.

Also generate:
  thumbnail.image_prompt — Bold dramatic scroll-stopping visual for the video's core message.
  High contrast, cinematic, close-up. 30+ words. Photorealistic. No text in frame.

Constraints:
  - Minimum 5 scenes, maximum 15 scenes.
  - covers_dialogue must use the EXACT words from the script (no paraphrasing).
  - Every word in the script must be covered by exactly one scene.

Return valid JSON only — no explanation, no markdown:
{{
  "thumbnail": {{"image_prompt": "..."}},
  "scenes": [
    {{
      "id": 1,
      "covers_dialogue": "exact words from script",
      "visual_type": "image",
      "image_prompt": "detailed prompt...",
      "pexels_query": null
    }},
    {{
      "id": 2,
      "covers_dialogue": "next dialogue span",
      "visual_type": "video",
      "image_prompt": null,
      "pexels_query": "search terms"
    }}
  ]
}}"""


# ── Validation ───────────────────────────────────────────────────────────────

def _validate_manifest(manifest: dict) -> tuple[bool, str]:
    if not isinstance(manifest, dict):
        return False, "Not a dict"
    if not manifest.get("thumbnail", {}).get("image_prompt"):
        return False, "Missing thumbnail.image_prompt"
    scenes = manifest.get("scenes", [])
    if not isinstance(scenes, list):
        return False, "scenes is not a list"
    if len(scenes) < 5:
        return False, f"Too few scenes: {len(scenes)} (min 5)"
    if len(scenes) > 15:
        return False, f"Too many scenes: {len(scenes)} (max 15)"
    for i, s in enumerate(scenes):
        if not s.get("covers_dialogue", "").strip():
            return False, f"Scene {i+1} missing covers_dialogue"
        if s.get("visual_type") not in ("image", "video"):
            return False, f"Scene {i+1} invalid visual_type"
        if s["visual_type"] == "image" and not s.get("image_prompt"):
            return False, f"Scene {i+1} is 'image' but missing image_prompt"
        if s["visual_type"] == "video" and not s.get("pexels_query"):
            return False, f"Scene {i+1} is 'video' but missing pexels_query"
    return True, ""


# ── Fallback: reconstruct from existing script beat data ─────────────────────

def _build_fallback_manifest(script: dict) -> dict:
    print("[visual_director] Building fallback manifest from script beat data")
    beat_visuals = script.get("beat_visuals", {})
    image_prompts = script.get("image_prompts", [""] * 5)

    insight = script.get("insight", "")
    half = len(insight) // 2

    sections = [
        (script.get("hook", ""),                  beat_visuals.get("beat_1", "image"), image_prompts[0] if len(image_prompts) > 0 else ""),
        (script.get("tension", ""),               beat_visuals.get("beat_2", "video"), image_prompts[1] if len(image_prompts) > 1 else ""),
        (insight[:half],                           beat_visuals.get("beat_3", "image"), image_prompts[2] if len(image_prompts) > 2 else ""),
        (insight[half:],                           beat_visuals.get("beat_4", "image"), image_prompts[3] if len(image_prompts) > 3 else ""),
        ((script.get("loopback", "") + " " + script.get("cta", "")).strip(),
                                                   beat_visuals.get("beat_5", "image"), image_prompts[4] if len(image_prompts) > 4 else ""),
    ]

    scenes = []
    for i, (dialogue, vtype, prompt) in enumerate(sections):
        if not dialogue.strip():
            continue
        pexels_q = " ".join(dialogue.split()[:4]) if vtype == "video" else None
        scenes.append({
            "id": i + 1,
            "covers_dialogue": dialogue.strip(),
            "visual_type": vtype,
            "image_prompt": prompt if vtype == "image" else None,
            "pexels_query": pexels_q,
        })

    return {
        "thumbnail": {"image_prompt": script.get("thumbnail_prompt",
            "Close-up of credit card on dark surface, dramatic side lighting, cinematic, photorealistic, HD")},
        "disclaimer": {"image_prompt":
            "Minimalist clean desk with notebook and pen, soft natural window light, no text, photorealistic, HD"},
        "scenes": scenes,
        "fallback": True,
    }


# ── Gemini call ───────────────────────────────────────────────────────────────

@retry(max_attempts=2, wait_seconds=8, exceptions=(Exception,))
def _call_gemini(prompt: str, model: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    # Prefer new SDK
    if _genai is not None:
        client = _genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )
        return json.loads(response.text)

    # Old SDK fallback
    if _genai_old is not None:
        _genai_old.configure(api_key=api_key)
        client = _genai_old.GenerativeModel(model)
        response = client.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    raise RuntimeError("No Gemini SDK available — install google-genai")


# ── Duration mapping (word-count proportional) ────────────────────────────────

def _assign_durations(manifest: dict, voice_duration: float) -> dict:
    """
    Assign start_sec / end_sec / duration_sec to each scene using word-count
    proportional timing against the total voice duration.
    Simple and reliable — TTS speed is roughly constant.
    """
    scenes = manifest["scenes"]
    word_counts = [max(1, len(s["covers_dialogue"].split())) for s in scenes]
    total_words = sum(word_counts)

    cursor = 0.0
    for scene, wc in zip(scenes, word_counts):
        duration = max(1.5, round((wc / total_words) * voice_duration, 3))
        scene["start_sec"] = round(cursor, 3)
        scene["end_sec"] = round(cursor + duration, 3)
        scene["duration_sec"] = duration
        cursor += duration

    return manifest


# ── Public entry points ───────────────────────────────────────────────────────

def run_visual_director(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[visual_director] Analysing script for {video_id}")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    voice_meta = load_json(os.path.join(run_dir, "03_voice_meta.json"))
    voice_duration = voice_meta["duration_sec"]

    parts = [script.get(k, "") for k in ("hook", "tension", "insight", "loopback", "cta")]
    raw_dialogue = " ".join(p for p in parts if p).strip()

    prompt = DIRECTOR_PROMPT.format(raw_dialogue=raw_dialogue)
    manifest = None

    try:
        manifest = _call_gemini(prompt, config.get("research_model", "gemini-2.5-flash"))
        valid, err = _validate_manifest(manifest)
        if not valid:
            print(f"[visual_director] Validation failed: {err} — retrying")
            retry_prompt = prompt + f"\n\nFIX REQUIRED: {err}. Return corrected JSON only."
            manifest = _call_gemini(retry_prompt, config.get("research_model", "gemini-2.5-flash"))
            valid, err = _validate_manifest(manifest)
            if not valid:
                raise ValueError(f"Still invalid after retry: {err}")
    except Exception as e:
        print(f"[visual_director] Gemini failed ({e}) — falling back to beat structure")
        manifest = _build_fallback_manifest(script)

    # Clamp to 5-15
    if len(manifest["scenes"]) > 15:
        manifest["scenes"] = manifest["scenes"][:15]
    if len(manifest["scenes"]) < 5:
        manifest = _build_fallback_manifest(script)

    # Re-number
    for i, s in enumerate(manifest["scenes"]):
        s["id"] = i + 1

    # Add timing
    manifest = _assign_durations(manifest, voice_duration)

    manifest["video_id"] = video_id
    manifest["total_scenes"] = len(manifest["scenes"])
    manifest["voice_duration"] = voice_duration
    manifest["generated_at"] = now_iso()

    output_path = os.path.join(run_dir, "03b_scene_manifest.json")
    save_json(manifest, output_path)

    n = manifest["total_scenes"]
    img_n = sum(1 for s in manifest["scenes"] if s["visual_type"] == "image")
    vid_n = n - img_n
    fb = " [FALLBACK]" if manifest.get("fallback") else ""
    print(f"[visual_director] Done. {n} scenes — {img_n} images, {vid_n} videos{fb}")
    return manifest


def run_visual_director_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[visual_director][MOCK] Building mock scene manifest for {video_id}")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    voice_meta = load_json(os.path.join(run_dir, "03_voice_meta.json"))
    voice_duration = voice_meta["duration_sec"]

    parts = [script.get(k, "") for k in ("hook", "tension", "insight", "loopback", "cta")]
    raw_dialogue = " ".join(p for p in parts if p).strip()
    words = raw_dialogue.split()

    # 5 evenly-split scenes, types: image video image image video
    vtypes = ["image", "video", "image", "image", "video"]
    labels = ["HOOK", "TENSION", "INSIGHT 1", "INSIGHT 2", "LOOPBACK"]
    chunk = max(1, len(words) // 5)
    scenes = []
    for i in range(5):
        start = i * chunk
        end = start + chunk if i < 4 else len(words)
        dialogue = " ".join(words[start:end])
        vtype = vtypes[i]
        scenes.append({
            "id": i + 1,
            "covers_dialogue": dialogue,
            "visual_type": vtype,
            "image_prompt": f"Mock photorealistic scene: {dialogue[:60]}, professional photography, HD" if vtype == "image" else None,
            "pexels_query": " ".join(words[start:start + 3]) if vtype == "video" else None,
            "label": labels[i],
        })

    manifest = {
        "video_id": video_id,
        "thumbnail": {"image_prompt": "Bold dramatic finance concept, high contrast, cinematic, photorealistic, HD"},
        "disclaimer": {"image_prompt": "Clean minimal professional desk, soft natural light, no text, photorealistic"},
        "scenes": scenes,
        "total_scenes": 5,
        "voice_duration": voice_duration,
        "generated_at": now_iso(),
    }

    manifest = _assign_durations(manifest, voice_duration)

    output_path = os.path.join(run_dir, "03b_scene_manifest.json")
    save_json(manifest, output_path)
    print(f"[visual_director][MOCK] Done. 5 mock scenes.")
    return manifest
