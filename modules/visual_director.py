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

DIRECTOR_PROMPT = """You are the visual director for Raccoon Economy — a US personal finance YouTube Shorts channel with a unique branded character universe.

SCRIPT (plain spoken dialogue, one scene per sentence):
"{raw_dialogue}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISUAL UNIVERSE — THE RACCOON ECONOMY WORLD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAIN CHARACTER — Regular Raccoon:
  Gray furry chibi raccoon, black mask around eyes, round ears.
  Always wears: gold chain necklace + white t-shirt.
  Expression range: deadpan → confused → alarmed → resigned → quietly determined.
  Lives in: cardboard box den with wooden table, warm lamp, small square window showing dark alley + glowing 7-Eleven sign.

SUPPORTING CHARACTERS (use when the dialogue calls for them):
  Animal Control Raccoon — gray chibi raccoon, full navy enforcement uniform, black aviator sunglasses, silver badge, clipboard, red OVERDUE stamp on belt. Always expressionless. Represents: IRS, government, any system that arrives whether you're ready or not.
  Smart Raccoon — gray chibi raccoon, sage green hoodie, round glasses, dark chinos, white sneakers, neat hair, upright posture. Always holds a document with a red circle. Quiet concern. Represents: financial advisor, the voice of reason Regular Raccoon ignores.
  Suit Raccoon (Bank Raccoon) — gray chibi raccoon, navy business suit, white shirt, gold pocket square, gold CAP VAULT chest badge, neat dark hair. Smiles with closed eyes and blush circles — serene and unsettling. Holds a pink credit card. Represents: financial institutions. Not your enemy. Not your friend.
  Crypto Raccoon — gray chibi raccoon, all-black hoodie with neon green accents, HODL belt buckle, WAGMI wristband, wild spiked dark hair. Stars in eyes when bullish, panic-wide eyes when bearish. Holds phone showing a chart. Represents: speculative finance, hype.

CURRENCY DISPLAY:
  NEVER show dollar signs or $ amounts in illustrated scenes.
  ALWAYS show money as CAPS — small round silver bottle caps stacked in piles.
  Translation: "$800 lost" → "800 CAPS rolling off a pile" | "$1,200 refund" → "1200 CAPS in a neat stack"
  Exception: Text on official-looking documents (pay stubs, tax forms) may show CAPS amounts.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCENE ASSIGNMENT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CORE RULE: One scene per sentence. Split dialogue into individual sentences. One unique scene each.

Scene 1 (hook) — HIGH ENERGY PATTERN INTERRUPT:
  Regular Raccoon in dramatic alarmed or deadpan-shocked pose. Bold close-up. This must stop the scroll.

For each scene pick a SCENE TYPE:
  • "reaction" — Regular Raccoon close-up or medium shot reacting to what was just said
  • "infographic" — flat graphic panel: CAPS pile, pay stub, chart, form, calculation breakdown (no character needed or just a paw visible)
  • "interaction" — two raccoon characters at table or doorway
  • "establishing" — wide shot of den or alley, sets the world
  • "object" — tight close-up of document, envelope, CAPS pile, form — maybe just a raccoon paw

Assign visual_type AND image_style for each scene. Target roughly equal thirds:

  visual_type "image", image_style "brand"  (~40% of scenes)
    → AI-generated Raccoon Economy chibi illustration
    → USE FOR: hook sentence, CTA, key emotional beats, raccoon character moments,
      infographic panels with CAPS piles, den/alley establishing shots
    → image_prompt must include raccoon character + end with chibi style string

  visual_type "image", image_style "context"  (~30% of scenes)
    → AI-generated contextual image — photorealistic OR clean flat infographic, NO raccoon
    → USE FOR: stat/fact moments, real-world financial concepts, US settings (bank branch,
      paycheck, tax form close-up, stock market board, apartment building)
    → image_prompt style: "photorealistic, professional photography, HD" OR "clean flat infographic"
    → Do NOT include chibi/cartoon/raccoon in context prompts

  visual_type "video"  (~30% of scenes)
    → Pexels stock footage — real human action and relatable scenes
    → USE FOR: "checking phone", "paying bills", "at work", "stressed person", "signing documents",
      anything with human movement and emotion
    → pexels_query: 3-5 word search term

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISUAL STYLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Style: flat cartoon, thick black outlines, solid fills, zero gradients, zero shadows, zero photorealism.
Think: Saturday morning cartoon meets financial nightmare. Roughness is intentional.
Background default: solid bright yellow #FFD700
Background exception: night/alley scenes use dark navy #1B2A4A; yellow always as accent
Color language: Yellow=world | Black=outlines | White=documents/tees | Red=danger/IRS/loss | Green=money/gains
NEVER: photorealistic, photography, 3D, gradients, shadows, complex textures

WORLD LOCATIONS (use these settings):
  The Alley — brick walls, single overhead lamp, dumpster labeled FIRST RACCOON BANK, 7-Eleven sign glowing. Dark charcoal + navy + yellow accents. The emotional anchor.
  The Den — cardboard box inside alley, wooden table, warm lamp, small square window.
  Cap Vault — Suit Raccoon's bank. Bold flat signage. Institutional.
  Pizza Hospital / Pizza Hotel / Pizza Palace — bold flat signage, no realistic detail.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
IMAGE PROMPT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For IMAGE scenes (image_style "brand") write a detailed image_prompt (40+ words):
  1. Scene type label (e.g. "Reaction shot:" or "Infographic panel:")
  2. Character present (or none for pure infographic)
  3. Specific action/pose/expression matching the dialogue
  4. What's on the table/in hands/visible in frame
  5. Setting detail (The Alley, The Den, Cap Vault, etc.)
  6. MUST end with: "flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"
  NEVER include: photorealistic, photography, gradients, shadows, 3D, digital art

For IMAGE scenes (image_style "context") write a detailed image_prompt (20+ words):
  Describe the real-world financial concept visually. No raccoon. No cartoon.
  End with: "photorealistic, professional photography, HD" OR "clean flat infographic, minimal design"
  Examples: "Close-up of a US bank statement with overdraft fees highlighted in red, photorealistic, professional photography, HD"
  NEVER include: raccoon, chibi, cartoon, flat cartoon, bright yellow, character

For VIDEO scenes: pexels_query with 3-5 word search term.

THUMBNAIL: Dramatic hook moment. Regular Raccoon in most alarmed/shocked pose of the video.
  image_style: "brand". End with: "flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - One scene per sentence. 6 minimum, 20 maximum.
  - covers_dialogue = EXACT words from the script (no paraphrasing).
  - Every word in the script covered by exactly one scene.

Return valid JSON only — no explanation, no markdown:
{{
  "thumbnail": {{"image_prompt": "Reaction shot: Regular Raccoon — gray chibi raccoon, gold chain, white tee — dramatic alarmed wide-eyed expression, cardboard den background. flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"}},
  "scenes": [
    {{
      "id": 1,
      "covers_dialogue": "exact words from script",
      "visual_type": "image",
      "image_style": "brand",
      "scene_type": "reaction",
      "image_prompt": "Reaction shot: Regular Raccoon [description]... flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical",
      "pexels_query": null
    }},
    {{
      "id": 2,
      "covers_dialogue": "next sentence",
      "visual_type": "image",
      "image_style": "context",
      "scene_type": "infographic",
      "image_prompt": "Close-up of a US bank statement with overdraft fees highlighted in red, photorealistic, professional photography, HD",
      "pexels_query": null
    }},
    {{
      "id": 3,
      "covers_dialogue": "another sentence",
      "visual_type": "video",
      "image_style": null,
      "scene_type": "reaction",
      "image_prompt": null,
      "pexels_query": "person checking bank account"
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
    if len(scenes) < 6:
        return False, f"Too few scenes: {len(scenes)} (min 6)"
    if len(scenes) > 20:
        return False, f"Too many scenes: {len(scenes)} (max 20)"
    for i, s in enumerate(scenes):
        if not s.get("covers_dialogue", "").strip():
            return False, f"Scene {i+1} missing covers_dialogue"
        if s.get("visual_type") not in ("image", "video"):
            return False, f"Scene {i+1} invalid visual_type"
        if s["visual_type"] == "image" and not s.get("image_prompt"):
            return False, f"Scene {i+1} is 'image' but missing image_prompt"
        if s["visual_type"] == "video" and not s.get("pexels_query"):
            return False, f"Scene {i+1} is 'video' but missing pexels_query"
        # Default image_style to "brand" if not set
        if s["visual_type"] == "image" and not s.get("image_style"):
            s["image_style"] = "brand"
        # For brand images only: ensure chibi style suffix is present
        if s["visual_type"] == "image" and s.get("image_style") == "brand" and s.get("image_prompt"):
            if "chibi art style" not in s["image_prompt"].lower():
                s["image_prompt"] += ", flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"
    # Thumbnail always brand — ensure chibi style
    thumb_prompt = manifest["thumbnail"]["image_prompt"]
    if "chibi art style" not in thumb_prompt.lower():
        manifest["thumbnail"]["image_prompt"] += ", flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"
    return True, ""


# ── Fallback: reconstruct from existing script beat data ─────────────────────

def _build_fallback_manifest(script: dict) -> dict:
    """Fallback: split full dialogue into sentences, one chibi scene per sentence."""
    import re
    print("[visual_director] Building fallback manifest — sentence-split chibi style")

    BRAND_STYLE = "flat cartoon style, thick black outlines, solid flat colors, bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"

    parts = [script.get(k, "") for k in ("hook", "tension", "insight", "loopback", "engagement_question", "cta")]
    full_text = " ".join(p for p in parts if p).strip()

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_text) if s.strip()]
    if not sentences:
        sentences = [full_text]

    # All images in fallback — chibi style
    scenes = []
    scene_types = ["reaction", "infographic", "reaction", "infographic", "reaction", "infographic"]
    for i, sentence in enumerate(sentences):
        stype = scene_types[i % len(scene_types)]
        if i == 0:
            stype = "reaction"
        img_prompt = (
            f"Reaction shot: Regular Raccoon — gray chibi raccoon, gold chain, white tee — "
            f"{'alarmed wide-eyed shocked expression' if i == 0 else 'deadpan confused expression'}, "
            f"sitting at wooden table in cardboard den, warm lamp in background. "
            f"Scene captures: {sentence[:60]}. {BRAND_STYLE}"
        )
        scenes.append({
            "id": i + 1,
            "covers_dialogue": sentence,
            "visual_type": "image",
            "scene_type": stype,
            "image_prompt": img_prompt,
            "pexels_query": None,
        })

    return {
        "thumbnail": {"image_prompt":
            f"Reaction shot: Regular Raccoon — gray chibi raccoon, gold chain, white tee — "
            f"dramatic alarmed wide-eyed expression, holding a document, sitting at wooden table. "
            f"{BRAND_STYLE}"},
        "disclaimer": {"image_prompt":
            f"Regular Raccoon — gray chibi raccoon, gold chain, white tee — sits at den table, "
            f"calm deadpan expression, small disclaimer card on table. {BRAND_STYLE}"},
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

    parts = [script.get(k, "") for k in ("hook", "tension", "insight", "loopback", "engagement_question", "cta")]
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

    # Clamp to 6-20
    if len(manifest["scenes"]) > 20:
        manifest["scenes"] = manifest["scenes"][:20]
    if len(manifest["scenes"]) < 6:
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
