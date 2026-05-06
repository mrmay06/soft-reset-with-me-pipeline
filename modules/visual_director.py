from __future__ import annotations

import os
import json
import re
import warnings

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry
from utils.script_contract import build_spoken_script_text

warnings.filterwarnings("ignore", category=FutureWarning, module="google")

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
except ImportError:
    _genai = None

# ── Prompt ───────────────────────────────────────────────────────────────────

DIRECTOR_PROMPT = """You are the visual director for Soft Reset With Me, a faceless US relationship/self-growth YouTube Shorts channel.
The channel uses cinematic stock footage plus kinetic typography. It should feel like a short film, not a productivity reel.

SCRIPT (plain spoken dialogue, grouped into synced asset beats):
"{raw_dialogue}"

CANONICAL BRAND BIBLE:
{brand_context}

VISUAL UNIVERSE - MOODY EDITORIAL CINEMA

Core mood:
- Cinematic stock footage and editorial stills
- Slightly desaturated warm tones, golden-hour light, intimate close-ups
- Faceless where possible: hands, silhouettes, back-of-head, reflections, empty chairs
- Feels like a private emotional moment
- Use candlelit rooms, rainy windows, hands writing, city nights, empty chairs, someone staring into distance, slow zoom shots
- The visual should feel like a private moment the viewer recognizes
- Favor real, cinematic stock-style footage over generated symbolic plates. This channel should feel like lived-in editorial B-roll, not AI poster art.

BRAND COLORS:
- Deep Midnight #1C1C2B for dark backgrounds and grounding
- Warm Terracotta #C4785A for hooks, CTA accents, and emotional emphasis
- Soft Cream #F5F0E8 for captions and overlays added in video editing, never inside generated images
- Sage Green #7BAE8A for healing and growth moments
- Avoid neon colors, busy backgrounds, bright sunny clips, fitness shots, and stock smiling couple poses

PALETTE FOR THIS VIDEO:
Use Deep Midnight as the base, Warm Terracotta as the primary accent, Soft Cream for text, and Sage Green only for healing/growth beats.

SCENE ASSIGNMENT RULES:
- One asset per 1-2 dialogue sentences
- Split dialogue into sentences first, then group them in order
- Each scene may cover one sentence or two adjacent sentences, never more
- The scene visual must directly represent the exact sentence(s) in covers_dialogue
- Do not assign generic visuals just to fill a slot

Scene 1 (hook):
- High-retention emotional close-up
- A faceless or near-faceless emotional image: rainy window, hand on notebook, empty chair, city night
- The hook image must stop the scroll without looking loud or cheap

Scene types:
- "reaction": faceless close-up of posture, hands, silhouette, reflection, or someone staring into distance
- "interaction": emotionally distant conversation with no stock-couple posing
- "object": empty chair, rain window, journal, candle, hand pausing over a closed notebook
- "establishing": city night, bedroom, candlelit room, rainy window, walking city, quiet apartment
- "infographic": minimal symbolic frame, such as an empty chair, candle, journal, doorway, or two cups left apart

Assign visual_type AND image_style for each scene:

VISUAL MIX RULES:
- Use video for 60-75% of scenes when possible
- Use generated brand images only for the hook, thumbnail, and symbolic beats that stock footage cannot express well
- Never place more than 2 generated still scenes back-to-back
- Every Pexels query in one manifest must be unique in wording and subject
- Avoid repeating the same subject composition twice in one short, especially person by window, journal close-up, and empty chair
- Progress the emotional sequence visually: waiting -> uncertainty -> clarity -> boundary -> release

visual_type "image", image_style "brand":
- Editorial still or generated cinematic background that matches the stock-footage look
- Use for hook frames, emotional background plates, and thumbnail background plates
- image_prompt must end with the cinematic style suffix below

visual_type "image", image_style "context":
- Clean photorealistic or minimal background plate
- Use sparingly for rooms, hands, journals, doors, or relatable modern details
- End with "photorealistic, professional photography, HD" OR "clean minimal graphic design"

visual_type "video":
- The asset generator randomly selects Pexels or Coverr by configured weights, then only falls back to generated imagery if that selected video provider fails
- Query must be 2-5 words and use specific emotional stock terms like: phone face down, rainy apartment window, city night walking, candlelit bedroom, hands closing journal, empty chair room, hallway night, person leaving room, coffee cup alone, train window night
- Never query for stock smiling couple poses, fitness, neon, bright sunny clips, mascots, cartoons, anime, or fantasy

IMAGE PROMPT RULES:
For brand image prompts, write 40+ words and include:
1. Scene type label
2. Faceless cinematic subject or object
3. Specific mood matching the dialogue
4. Journal/window/chair/candle/hand action visible. Avoid phones in generated image prompts; use phone scenes mostly as stock video queries.
5. Modern intimate setting
6. Brand color wording
7. MUST end with:
"moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, Warm Terracotta practical light accent, real-world photographic scene only, continuous natural background surfaces, window glass, candlelight, furniture, closed journal, hands, and shadows only, unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, intimate close-up, shallow depth of field, faceless composition, 9:16 vertical"

Do not put the spoken words from covers_dialogue into image_prompt. If the dialogue says "maybe", "yes", "no", "confusion", "save", or any other literal word, translate it into an object/action instead. Generated images are vibe plates only; all words are added later by captions.
For generated images, avoid phones and screens by default. If the script needs a phone moment, prefer visual_type "video" with a stock query like "phone face down".
For journal shots, pages must be blank, blurred, closed, or turned away. Never ask for written words, sparse words, handwriting lines, lists, or readable notes.

For context images, no anime wording. Keep it real, moody, simple, and free of visible text.

TEXT OVERLAY DIRECTION:
- Hook text: large centered DM Serif Display style, Soft Cream, emotional and sparse
- Body/list text: Inter Bold style, high contrast
- Use dark semi-transparent scrim if the background is light
- Each key phrase should get its own screen moment
- Hook fades in. Key insight snaps in with a slight scale-up.
- Text overlays are added by the video/caption system only. Generated images must not contain any words.

THUMBNAIL:
- Use the most emotionally specific hook moment
- Compose naturally with darker edges or shadow areas that can support later typography
- Faceless, moody, cinematic
- Generated thumbnail background must contain no visible text, no words, no letters, no captions, and no signage
- End with the same cinematic style suffix
- Keep it as a real photographed environment, not a graphic composition.

CONSTRAINTS:
- 20 scenes maximum
- covers_dialogue = EXACT words from the script
- Every word in the script must be covered by exactly one scene
- Each image_prompt or pexels_query must clearly match its own covers_dialogue

Return valid JSON only - no explanation, no markdown:
{{
  "palette": {{
    "base": "#1C1C2B",
    "accent": "#C4785A",
    "text": "#F5F0E8",
    "healing": "#7BAE8A"
  }},
  "thumbnail": {{"image_prompt": "Editorial hook frame: faceless person sitting near a rainy window at night, closed journal on the table, empty chair in the background, warm candle glow, real-world photographic scene only, continuous natural background surfaces, unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, Warm Terracotta practical light accent, intimate close-up, shallow depth of field, faceless composition, 9:16 vertical"}},
  "scenes": [
    {{
      "id": 1,
      "covers_dialogue": "exact words from script",
      "visual_type": "image",
      "image_style": "brand",
      "scene_type": "reaction",
      "image_prompt": "Reaction shot: [description]... real-world photographic scene only, continuous natural background surfaces, unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, Warm Terracotta practical light accent, intimate close-up, shallow depth of field, faceless composition, 9:16 vertical",
      "pexels_query": null
    }},
    {{
      "id": 2,
      "covers_dialogue": "next sentence",
      "visual_type": "video",
      "image_style": null,
      "scene_type": "object",
      "image_prompt": null,
      "pexels_query": "rainy apartment window"
    }}
  ]
}}"""


# ── Validation ───────────────────────────────────────────────────────────────

def _dialogue_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9'$%.-]+", text.lower())


def _split_dialogue_sentences(text: str) -> list[str]:
    sentences = re.findall(r"[^.!?]+[.!?]+(?:['\"])?|[^.!?]+$", text)
    return [s.strip() for s in sentences if s.strip()]


def _validate_manifest(manifest: dict, raw_dialogue: str | None = None) -> tuple[bool, str]:
    if not isinstance(manifest, dict):
        return False, "Not a dict"
    if not manifest.get("thumbnail", {}).get("image_prompt"):
        return False, "Missing thumbnail.image_prompt"
    scenes = manifest.get("scenes", [])
    if not isinstance(scenes, list):
        return False, "scenes is not a list"
    if len(scenes) > 20:
        return False, f"Too many scenes: {len(scenes)} (max 20)"
    expected_sentences = _split_dialogue_sentences(raw_dialogue) if raw_dialogue else []
    if expected_sentences:
        min_scenes = max(1, (len(expected_sentences) + 1) // 2)
        if len(scenes) < min_scenes:
            return False, f"Too few scenes: {len(scenes)} (need at least {min_scenes} for 1-2 sentences per scene)"
        if len(scenes) > len(expected_sentences):
            return False, f"Too many scenes: {len(scenes)} for {len(expected_sentences)} sentences"
    if len(scenes) >= 6:
        video_count = sum(1 for s in scenes if s.get("visual_type") == "video")
        if video_count < len(scenes) // 2:
            return False, f"Too few stock video scenes: {video_count}/{len(scenes)}"
    seen_queries: set[str] = set()
    consecutive_images = 0
    for i, s in enumerate(scenes):
        if not s.get("covers_dialogue", "").strip():
            return False, f"Scene {i+1} missing covers_dialogue"
        if len(_split_dialogue_sentences(s["covers_dialogue"])) > 2:
            return False, f"Scene {i+1} covers more than 2 dialogue sentences"
        if s.get("visual_type") not in ("image", "video"):
            return False, f"Scene {i+1} invalid visual_type"
        if s["visual_type"] == "image":
            consecutive_images += 1
            if consecutive_images > 2:
                return False, f"Scene {i+1} creates more than 2 generated stills in a row"
        else:
            consecutive_images = 0
        if s["visual_type"] == "image" and not s.get("image_prompt"):
            return False, f"Scene {i+1} is 'image' but missing image_prompt"
        if s["visual_type"] == "video" and not s.get("pexels_query"):
            return False, f"Scene {i+1} is 'video' but missing pexels_query"
        if s["visual_type"] == "video":
            query = re.sub(r"\s+", " ", s.get("pexels_query", "").strip().lower())
            if query in seen_queries:
                return False, f"Scene {i+1} repeats Pexels query '{query}'"
            seen_queries.add(query)
        # Default image_style to "brand" if not set
        if s["visual_type"] == "image" and not s.get("image_style"):
            s["image_style"] = "brand"
        # For brand images only: ensure the cinematic style suffix is present
        if s["visual_type"] == "image" and s.get("image_style") == "brand" and s.get("image_prompt"):
            if re.search(r"\b(maybe|confusion|possibility)\b", s["image_prompt"], flags=re.IGNORECASE):
                return False, f"Scene {i+1} image_prompt contains literal dialogue text"
            if "moody editorial cinematic" not in s["image_prompt"].lower():
                s["image_prompt"] += ", real-world photographic scene only, continuous natural background surfaces, window glass, candlelight, furniture, closed journal, hands, and shadows only, unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, Warm Terracotta practical light accent, intimate close-up, shallow depth of field, faceless composition, 9:16 vertical"
    if raw_dialogue:
        expected = _dialogue_words(raw_dialogue)
        covered = _dialogue_words(" ".join(s.get("covers_dialogue", "") for s in scenes))
        if covered != expected:
            return False, "Scene dialogue coverage does not match script exactly"
    # Thumbnail always brand — ensure cinematic style
    thumb_prompt = manifest["thumbnail"]["image_prompt"]
    if "moody editorial cinematic" not in thumb_prompt.lower():
        manifest["thumbnail"]["image_prompt"] += ", real-world photographic scene only, continuous natural background surfaces, window glass, candlelight, furniture, closed journal, hands, and shadows only, unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, Warm Terracotta practical light accent, intimate close-up, shallow depth of field, faceless composition, 9:16 vertical"
    return True, ""


# ── Fallback: reconstruct from existing script beat data ─────────────────────

def _build_fallback_manifest(script: dict) -> dict:
    """Fallback: group dialogue into synced 1-2 sentence cinematic assets."""
    print("[visual_director] Building fallback manifest — synced cinematic style")

    BRAND_STYLE = (
        "moody editorial cinematic still, slightly desaturated warm tones, "
        "Deep Midnight base, Warm Terracotta practical light accent, "
        "real-world photographic scene only, continuous natural background surfaces, "
        "window glass, candlelight, furniture, closed journal, hands, and shadows only, "
        "unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, intimate close-up, "
        "shallow depth of field, faceless composition, 9:16 vertical"
    )

    full_text = build_spoken_script_text(script)

    sentences = _split_dialogue_sentences(full_text)
    if not sentences:
        sentences = [full_text]

    # Keep the fallback punchy: short beats get paired, but the hook and
    # metaphor lines get their own visual moments.
    pattern = [1, 1, 2, 2, 2, 2, 2, 1, 1, 2]
    groups = []
    i = 0
    for take in pattern:
        if i >= len(sentences):
            break
        groups.append(" ".join(sentences[i:i + take]))
        i += take
    while i < len(sentences):
        remaining = len(sentences) - i
        take = 1 if remaining == 1 else 2
        groups.append(" ".join(sentences[i:i + take]))
        i += take

    def fallback_query_for(dialogue: str, idx: int) -> str:
        text = dialogue.lower()
        if "hallway" in text:
            return "hallway night"
        if "closing a door" in text or "not closing" in text:
            return "hand on door handle"
        if "saying no" in text or "honest" in text:
            return "person leaving room"
        if "wants you" in text or "answer" in text:
            return "dark empty chair"
        if "clear" in text or "confusion" in text:
            return "candlelit room"
        if "uncertainty" in text or "possibility" in text:
            return "city night walking"
        if "waiting" in text or "decoding" in text:
            return "phone face down"
        if "save this" in text or "cost you" in text:
            return "phone at night"
        return [
            "rainy apartment window",
            "hands closing journal",
            "train window night",
            "coffee cup alone",
        ][idx % 4]

    scenes = []
    for idx, dialogue in enumerate(groups):
        use_image = idx in (0, 4, len(groups) - 1)
        stype = "reaction" if idx == 0 else ("object" if use_image else "establishing")
        img_prompt = None
        query = fallback_query_for(dialogue, idx)
        if use_image:
            img_prompt = (
                f"Editorial shot: faceless person in a candlelit apartment, "
                f"{'closed journal and hand resting beside it' if idx == 0 else 'closed journal, empty chair, and warm practical lamp in frame'}, "
                f"quiet intimate room, real photographed environment, continuous walls and shadows, no graphic overlay. "
                f"{BRAND_STYLE}"
            )
        scenes.append({
            "id": idx + 1,
            "covers_dialogue": dialogue,
            "visual_type": "image" if use_image else "video",
            "image_style": "brand" if use_image else None,
            "scene_type": stype,
            "image_prompt": img_prompt,
            "pexels_query": query,
        })

    return {
        "thumbnail": {"image_prompt":
            f"Editorial hook frame: faceless person sitting beside a rainy window, closed journal on the table, "
            f"empty chair in background, candlelit room, real photographed environment, continuous walls and shadows, no graphic overlay. "
            f"{BRAND_STYLE}"},
        "palette": {
            "base": "#1C1C2B",
            "accent": "#C4785A",
            "text": "#F5F0E8",
            "healing": "#7BAE8A",
        },
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
    try:
        import google.generativeai as _genai_old
    except ImportError:
        _genai_old = None

    if _genai_old is not None:
        _genai_old.configure(api_key=api_key)
        client = _genai_old.GenerativeModel(model)
        response = client.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        )
        return json.loads(response.text)

    raise RuntimeError("No Gemini SDK available — install google-genai")


def _load_brand_context() -> str:
    path = "config/brand_characters.json"
    if not os.path.exists(path):
        return "No brand character config found."
    try:
        return json.dumps(load_json(path), indent=2)
    except Exception as e:
        return f"Brand character config could not be loaded: {e}"


# ── Duration mapping (word-count proportional) ────────────────────────────────

def _assign_durations(manifest: dict, voice_duration: float) -> dict:
    """
    Assign start_sec / end_sec / duration_sec to each scene using word-count
    proportional timing against the total voice duration.
    Simple and reliable — TTS speed is roughly constant.
    """
    scenes = manifest["scenes"]
    min_scene_duration = 1.5
    word_counts = [max(1, len(s["covers_dialogue"].split())) for s in scenes]
    total_words = sum(word_counts)

    cursor = 0.0
    if len(scenes) * min_scene_duration >= voice_duration:
        durations = [voice_duration / len(scenes)] * len(scenes)
    else:
        remaining = voice_duration - (len(scenes) * min_scene_duration)
        durations = [
            min_scene_duration + ((wc / total_words) * remaining)
            for wc in word_counts
        ]

    for scene, wc in zip(scenes, word_counts):
        duration = round(durations.pop(0), 3)
        scene["start_sec"] = round(cursor, 3)
        scene["end_sec"] = round(cursor + duration, 3)
        scene["duration_sec"] = duration
        cursor += duration

    if scenes:
        scenes[-1]["end_sec"] = round(voice_duration, 3)
        scenes[-1]["duration_sec"] = round(scenes[-1]["end_sec"] - scenes[-1]["start_sec"], 3)

    return manifest


# ── Public entry points ───────────────────────────────────────────────────────

def run_visual_director(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[visual_director] Analysing script for {video_id}")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    voice_meta = load_json(os.path.join(run_dir, "03_voice_meta.json"))
    voice_duration = voice_meta["duration_sec"]

    raw_dialogue = build_spoken_script_text(script)

    from utils.strategy import inject_strategy
    prompt = inject_strategy(DIRECTOR_PROMPT, "visuals").format(
        raw_dialogue=raw_dialogue,
        brand_context=_load_brand_context(),
    )
    manifest = None

    try:
        manifest = _call_gemini(prompt, config.get("research_model", "gemini-2.5-flash"))
        valid, err = _validate_manifest(manifest, raw_dialogue)
        if not valid:
            print(f"[visual_director] Validation failed: {err} — retrying")
            retry_prompt = prompt + f"\n\nFIX REQUIRED: {err}. Return corrected JSON only."
            manifest = _call_gemini(retry_prompt, config.get("research_model", "gemini-2.5-flash"))
            valid, err = _validate_manifest(manifest, raw_dialogue)
            if not valid:
                raise ValueError(f"Still invalid after retry: {err}")
    except Exception as e:
        print(f"[visual_director] Gemini failed ({e}) — falling back to beat structure")
        manifest = _build_fallback_manifest(script)

    # Clamp to max supported scene count. If clamping breaks dialogue coverage,
    # validation below will force the deterministic fallback.
    if len(manifest["scenes"]) > 20:
        manifest["scenes"] = manifest["scenes"][:20]
    valid, err = _validate_manifest(manifest, raw_dialogue)
    if not valid:
        print(f"[visual_director] Manifest post-check failed: {err} — using fallback")
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

    raw_dialogue = build_spoken_script_text(script)
    sentences = _split_dialogue_sentences(raw_dialogue)
    groups = []
    i = 0
    while i < len(sentences):
        remaining = len(sentences) - i
        take = 1 if remaining == 1 else 2
        groups.append(" ".join(sentences[i:i + take]))
        i += take

    vtypes = ["image", "video", "video", "image", "video", "video"]
    mock_queries = [
        "phone face down",
        "rainy apartment window",
        "city night walking",
        "hands closing journal",
        "hallway night",
        "person leaving room",
    ]
    scenes = []
    for i, dialogue in enumerate(groups):
        vtype = vtypes[i % len(vtypes)]
        image_prompt = (
            f"Mock cinematic stock-style relationship scene: faceless person near a rainy apartment window, "
            f"closed journal, candlelit room, empty chair, real photographed environment, continuous walls and shadows, "
            f"moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, "
            f"Warm Terracotta practical light accent, unedited camera frame, no graphic overlay, "
            f"no captions, no signage, no readable screens, "
            f"intimate close-up, shallow depth of field, faceless composition, 9:16 vertical"
        )
        scenes.append({
            "id": i + 1,
            "covers_dialogue": dialogue,
            "visual_type": vtype,
            "image_style": "brand" if vtype == "image" else None,
            "scene_type": "reaction" if i == 0 else "object",
            "image_prompt": image_prompt if vtype == "image" else None,
            "pexels_query": mock_queries[i % len(mock_queries)] if vtype == "video" else None,
            "label": f"SCENE {i + 1}",
        })

    manifest = {
        "video_id": video_id,
        "palette": {
            "base": "#1C1C2B",
            "accent": "#C4785A",
            "text": "#F5F0E8",
            "healing": "#7BAE8A",
        },
        "thumbnail": {"image_prompt": "Faceless person sitting beside rainy window, closed journal, candlelit room, empty chair, real photographed environment, continuous walls and shadows, unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, moody editorial cinematic still, slightly desaturated warm tones, Deep Midnight base, Warm Terracotta practical light accent, intimate close-up, shallow depth of field, faceless composition, 9:16 vertical"},
        "scenes": scenes,
        "total_scenes": len(scenes),
        "voice_duration": voice_duration,
        "generated_at": now_iso(),
    }

    manifest = _assign_durations(manifest, voice_duration)

    output_path = os.path.join(run_dir, "03b_scene_manifest.json")
    save_json(manifest, output_path)
    print(f"[visual_director][MOCK] Done. {len(scenes)} mock scenes.")
    return manifest
