from __future__ import annotations

import os
import shutil
import subprocess
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFont  # noqa: F401 — ImageDraw/ImageFont used in _draw_text_overlay

from utils.helpers import load_json, save_json, now_iso

MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024


def _extract_frame(video_path: str, output_path: str, at_sec: float):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_sec), "-i", video_path, "-vframes", "1", "-q:v", "2", output_path],
        check=True,
        capture_output=True,
    )


def _resize_to_target(path_in: str, path_out: str, width: int, height: int):
    image = Image.open(path_in).convert("RGB")
    image = image.resize((width, height), Image.LANCZOS)
    image.save(path_out)


def _save_png_under_limit(image: Image.Image, output_path: str) -> bool:
    image.save(output_path, optimize=True)
    if os.path.getsize(output_path) <= MAX_THUMBNAIL_BYTES:
        return False
    # YouTube thumbnails must be under 2MB. Adaptive PNG quantization keeps the
    # existing .png upload path while avoiding oversized photorealistic renders.
    quantized = image.convert("P", palette=Image.ADAPTIVE, colors=256)
    quantized.save(output_path, optimize=True)
    return os.path.getsize(output_path) <= MAX_THUMBNAIL_BYTES


def _sanitize_thumb_text(text: str, max_words: int = 5, uppercase: bool = True) -> str:
    """Normalize to ASCII-safe thumbnail copy."""
    replacements = {"≠": "!=", "→": ">", "—": "-", "–": "-", "'": "'", "'": "'",
                    "“": '"', "”": '"', "…": "...", "é": "e", "è": "e"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = " ".join(text.split())
    words = text.split()
    cleaned = " ".join(words[:max_words]).strip()
    return cleaned.upper() if uppercase else cleaned.lower()


def _variant_copy(variant: dict) -> tuple[str, str, str]:
    line1 = _sanitize_thumb_text(variant.get("line1", ""), max_words=4, uppercase=True)
    line2 = _sanitize_thumb_text(variant.get("line2", ""), max_words=6, uppercase=False)
    if not line1:
        legacy = _sanitize_thumb_text(variant.get("thumbnail_text", ""), max_words=4, uppercase=True)
        line1 = legacy or "YOU ALREADY KNOW"
    if not line2:
        line2 = "this is why it hurts"
    combined = f"{line1} / {line2}"
    return line1, line2, combined


def _fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: str, start_size: int, max_width: int, min_size: int):
    size = max(start_size, min_size)
    try:
        font = ImageFont.truetype(font_path, size=size)  # noqa: F821
    except Exception:
        font = ImageFont.load_default()  # noqa: F821
    while size >= min_size:
        try:
            font = ImageFont.truetype(font_path, size=size)  # noqa: F821
        except Exception:
            font = ImageFont.load_default()  # noqa: F821
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=max(2, size // 18))
        if bbox[2] - bbox[0] <= max_width:
            return font, size
        size -= 4
    return font, size


def _draw_text_overlay(image_path: str, line1: str, line2: str, variant_id: str, width: int, height: int) -> None:
    """Bake the two-line thumbnail system with PIL for exact, readable text."""
    if not line1 and not line2:
        return
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)  # noqa: F821

    inter = "assets/fonts/Inter-Bold.ttf"
    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    left = int(width * 0.075)
    top = int(height * 0.22)
    max_width = int(width * 0.36)
    line1_font, line1_size = _fit_font(draw, line1, inter, int(height * 0.118), max_width, int(height * 0.066))
    line2_font, line2_size = _fit_font(draw, line2, inter, int(line1_size * 0.58), max_width, int(height * 0.042))
    stroke = max(5, line1_size // 13)
    shadow = max(4, line1_size // 12)

    draw.text((left + shadow, top + shadow), line1, font=line1_font, fill=BLACK, stroke_width=stroke, stroke_fill=BLACK)
    draw.text((left, top), line1, font=line1_font, fill=WHITE, stroke_width=stroke, stroke_fill=BLACK)

    line1_box = draw.textbbox((left, top), line1, font=line1_font, stroke_width=stroke)
    line2_y = line1_box[3] + int(height * 0.035)
    draw.text((left + 2, line2_y + 2), line2, font=line2_font, fill=(0, 0, 0))
    draw.text((left, line2_y), line2, font=line2_font, fill=(235, 235, 235))

    compressed = _save_png_under_limit(img, image_path)
    print(f"[longform_thumbnail] Text overlay applied: '{line1}' / '{line2}' (variant {variant_id})")
    if compressed:
        print("[longform_thumbnail] Thumbnail PNG optimized under 2MB")


def _build_generation_prompt(research: dict, variant: dict) -> str:
    topic = str(research.get("topic", "") or "relationship healing").strip()
    visual_context = str(variant.get("visual_prompt", "") or "").strip()
    mood = {
        "A": "introspective and premium",
        "B": "raw and emotionally immediate",
        "C": "counter-intuitive and quietly intense",
    }.get(variant.get("id"), "introspective")
    return (
        "Generate a 1280x720 photorealistic cinematic YouTube thumbnail background with NO TEXT. "
        "One young adult face in close-up fills the right 55 to 65 percent of the frame. "
        "The left 35 to 40 percent of the frame is clean dark negative space for text, completely empty. "
        "Expression: quiet devastated recognition, heavy eyes, direct camera contact, lips softly parted or gently closed. "
        "No smile, no open-mouth shock, no obvious crying, no performed drama. "
        "Camera at eye level or slightly below eye level. Tight crop: face and upper shoulder only. "
        "Loose natural slightly disheveled hair, simple dark or neutral clothing with no logos and no patterns. "
        "Lighting: soft diffused cool-neutral daylight from a large overcast window. "
        "Do not use warm amber light, golden hour, candlelight, orange tones, teal tones, or blue-green color cast. "
        "Background: completely out-of-focus neutral dark gray, no identifiable location, no sharp objects, no text, no UI. "
        "Natural skin texture with visible pores, subtle film grain, slightly desaturated prestige drama color grade. "
        "No watermarks, no borders, no logos. No important elements in the bottom-right 15 percent. "
        "Maximum three visual elements total: face, background, empty text zone. "
        f'The emotional context is "{topic}". Mood is {mood}. '
        f"Additional visual context to translate subtly without adding objects or text: {visual_context}"
    )


def _generate_gemini_thumbnail(prompt: str, output_path: str) -> bool:
    """Try Gemini imagen as secondary image source. Returns True on success."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        return False
    try:
        from google import genai as _genai
        from google.genai import types as _genai_types
        client = _genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.0-flash-preview-image-generation",
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
            ),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.data:
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                return True
    except Exception as exc:
        print(f"[longform_thumbnail] Gemini imagen failed: {exc}")
    return False


def _generate_pollinations_thumbnail(prompt: str, output_path: str, width: int, height: int) -> bool:
    api_key = os.environ.get("POLLINATIONS_API_KEY", "")
    encoded = urllib.parse.quote(prompt, safe="")
    url = (
        f"https://gen.pollinations.ai/image/{encoded}"
        f"?model=gptimage&width={width}&height={height}&seed=0&enhance=false&key={api_key}"
    )
    try:
        response = requests.get(url, timeout=90)
        if response.status_code == 200 and len(response.content) > 10000:
            with open(output_path, "wb") as f:
                f.write(response.content)
            return True
        print(f"[longform_thumbnail] Pollinations failed: status={response.status_code} size={len(response.content)}")
    except Exception as exc:
        print(f"[longform_thumbnail] Pollinations failed: {exc}")
    return False


def run_longform_thumbnail(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[longform_thumbnail] Creating A/B/C thumbnails for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    render_meta = load_json(os.path.join(run_dir, "06_longform_render_meta.json"))
    video_path = os.path.join(run_dir, "06_longform_video.mp4")
    width = int(config.get("longform_thumbnail_width", 1280))
    height = int(config.get("longform_thumbnail_height", 720))
    primary_id = str(metadata.get("primary_variant_id", "B")).upper()

    generated_variants = []
    for variant in metadata.get("thumbnail_variants", []):
        variant_id = str(variant.get("id", "")).upper()
        if variant_id not in {"A", "B", "C"}:
            continue
        line1, line2, thumb_text = _variant_copy(variant)
        prompt = _build_generation_prompt(research, variant)
        prompt_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}_prompt.txt")
        generated_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}_generated.png")
        output_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}.png")
        frame_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}_frame.jpg")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        # Image source priority: Pollinations → Gemini imagen → video frame
        gemini_generated_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}_gemini.png")
        generated = _generate_pollinations_thumbnail(prompt, generated_path, width, height)
        if generated:
            _resize_to_target(generated_path, output_path, width, height)
            source = "pollinations_gptimage"
        elif _generate_gemini_thumbnail(prompt, gemini_generated_path):
            _resize_to_target(gemini_generated_path, output_path, width, height)
            source = "gemini_imagen"
        else:
            duration = float(render_meta.get("duration_sec", 300))
            _extract_frame(video_path, frame_path, at_sec=max(8, duration * 0.18))
            _resize_to_target(frame_path, output_path, width, height)
            source = "video_frame_fallback"

        # Always bake text via PIL — guarantees legibility regardless of image source
        _draw_text_overlay(output_path, line1, line2, variant_id, width, height)

        raw_generated = (
            generated_path if source == "pollinations_gptimage" else
            gemini_generated_path if source == "gemini_imagen" else
            frame_path if os.path.exists(frame_path) else ""
        )
        generated_variants.append({
            "id": variant_id,
            "angle": variant.get("angle", ""),
            "pattern": variant.get("pattern", ""),
            "line1": line1,
            "line2": line2,
            "thumbnail_text": thumb_text,
            "prompt_file": os.path.basename(prompt_path),
            "generated_file": os.path.basename(raw_generated) if raw_generated and os.path.exists(raw_generated) else "",
            "output_file": os.path.basename(output_path),
            "background_source": source,
            "final_output_size": f"{width}x{height}",
            "degraded_fallback": source == "video_frame_fallback",
        })
        print(f"[longform_thumbnail] Variant {variant_id} ready ({source})")

    primary = next((item for item in generated_variants if item["id"] == primary_id), generated_variants[0])
    primary_output = os.path.join(run_dir, primary["output_file"])
    final_output = os.path.join(run_dir, "07_longform_thumbnail.png")
    if os.path.abspath(primary_output) != os.path.abspath(final_output):
        shutil.copyfile(primary_output, final_output)

    meta_path = os.path.join(run_dir, "07_longform_thumbnail_meta.json")
    save_json({
        "video_id": video_id,
        "output": "07_longform_thumbnail.png",
        "primary_variant_id": primary["id"],
        "primary_output_file": primary["output_file"],
        "thumbnail_strategy": "longform_ab_packaging_v2",
        "variants": generated_variants,
        "generated_at": now_iso(),
    }, meta_path)
    print(f"[longform_thumbnail] Done. Primary variant [{primary['id']}] -> {final_output}")
    return final_output


def run_longform_thumbnail_mock(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[longform_thumbnail][MOCK] Creating lightweight thumbnail variants for {video_id}")
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    width = int(config.get("longform_thumbnail_width", 1280))
    height = int(config.get("longform_thumbnail_height", 720))
    primary_id = str(metadata.get("primary_variant_id", "B")).upper()
    variants = metadata.get("thumbnail_variants", []) or [
        {"id": "A", "thumbnail_text": "MISS THE DREAM"},
        {"id": "B", "thumbnail_text": "NOT THE PERSON"},
        {"id": "C", "thumbnail_text": "LET THE MAYBE GO"},
    ]
    generated_variants = []
    for variant in variants:
        variant_id = str(variant.get("id", "")).upper()
        if variant_id not in {"A", "B", "C"}:
            continue
        output_file = f"07_longform_thumbnail_{variant_id}.png"
        output_path = os.path.join(run_dir, output_file)
        image = Image.new("RGB", (width, height), (28, 28, 43))
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, width, 20), fill=(196, 120, 90))
        draw.rectangle((0, height - 20, width, height), fill=(123, 174, 138))
        image.save(output_path)
        line1, line2, thumb_text = _variant_copy(variant)
        _draw_text_overlay(output_path, line1, line2, variant_id, width, height)
        generated_variants.append({
            "id": variant_id,
            "angle": variant.get("angle", "mock"),
            "pattern": variant.get("pattern", "mock"),
            "line1": line1,
            "line2": line2,
            "thumbnail_text": thumb_text,
            "prompt_file": "",
            "generated_file": "",
            "output_file": output_file,
            "background_source": "mock",
            "final_output_size": f"{width}x{height}",
            "degraded_fallback": False,
        })
    primary = next((item for item in generated_variants if item["id"] == primary_id), generated_variants[0])
    final_output = os.path.join(run_dir, "07_longform_thumbnail.png")
    shutil.copyfile(os.path.join(run_dir, primary["output_file"]), final_output)
    save_json({
        "video_id": video_id,
        "output": "07_longform_thumbnail.png",
        "primary_variant_id": primary["id"],
        "primary_output_file": primary["output_file"],
        "thumbnail_strategy": "mock_longform_ab_packaging",
        "variants": generated_variants,
        "generated_at": now_iso(),
    }, os.path.join(run_dir, "07_longform_thumbnail_meta.json"))
    print(f"[longform_thumbnail][MOCK] Done. Primary variant [{primary['id']}]")
    return final_output
