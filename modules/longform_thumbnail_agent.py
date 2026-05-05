from __future__ import annotations

import os
import shutil
import subprocess
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageFont

from utils.helpers import load_json, save_json, now_iso


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


def _sanitize_thumb_text(text: str) -> str:
    """Normalize to ASCII-safe uppercase, max 5 words."""
    replacements = {"≠": "!=", "→": ">", "—": "-", "–": "-", "‘": "'", "’": "'",
                    "“": '"', "”": '"', "…": "...", "é": "e", "è": "e"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    words = text.upper().split()
    return " ".join(words[:5]).strip()


def _draw_text_overlay(image_path: str, thumb_text: str, variant_id: str, width: int, height: int) -> None:
    """Bake brand text onto thumbnail with PIL — guaranteed legibility regardless of image source."""
    if not thumb_text:
        return
    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    font_size = max(72, height // 8)
    try:
        font = ImageFont.truetype("assets/fonts/DMSerifDisplay-Regular.ttf", size=font_size)
    except Exception:
        try:
            font = ImageFont.truetype("assets/fonts/Inter-Bold.ttf", size=font_size)
        except Exception:
            font = ImageFont.load_default()

    TERRACOTTA = (196, 120, 90)
    CREAM = (245, 240, 232)
    BLACK = (0, 0, 0)

    # A & C text on left zone; B on right (matches prompt side logic)
    text_on_left = variant_id in {"A", "C"}
    zone_cx = int(width * 0.25) if text_on_left else int(width * 0.75)
    max_line_w = int(width * 0.42)

    words = thumb_text.upper().split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_line_w or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    lines = lines[:3]

    line_h = int(font_size * 1.18)
    total_h = len(lines) * line_h
    y = (height - total_h) // 2
    stroke = max(5, font_size // 16)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = int(zone_cx - tw / 2)
        color = TERRACOTTA if i == len(lines) - 1 else CREAM
        # Heavy black stroke for legibility on any background
        for dx in range(-stroke, stroke + 1, stroke):
            for dy in range(-stroke, stroke + 1, stroke):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), line, font=font, fill=BLACK)
        draw.text((x, y), line, font=font, fill=color)
        y += line_h

    img.save(image_path)
    print(f"[longform_thumbnail] Text overlay applied: '{thumb_text}' (variant {variant_id})")


def _build_generation_prompt(research: dict, variant: dict) -> str:
    topic = str(research.get("topic", "") or "relationship healing").strip()
    pattern = str(variant.get("pattern", "clean_concept_close_up")).strip()
    thumb_text = str(variant.get("thumbnail_text", "")).strip()
    text_zone = "left" if variant.get("id") in {"A", "C"} else "right"
    visual_zone = "right" if text_zone == "left" else "left"
    text_style = "extra bold heavy serif uppercase" if pattern in {"clean_concept_close_up", "subject_vs_the_void", "dichotomy_split"} else "extra bold heavy sans-serif uppercase"
    text_color = "#C4785A" if variant.get("id") in {"A", "B"} else "#F5F0E8"
    prompt_by_pattern = {
        "clean_concept_close_up": (
            f"The {visual_zone} half shows a single emotional subject taking up about 60% of the frame, in three-quarter profile, "
            "lit from one side with warm terracotta light and deep midnight shadow, showing genuine exhaustion, realization, grief, or quiet determination. "
            f"The {text_zone} half contains clean dark negative space for the text zone."
        ),
        "highlighted_truth": (
            "The background is a blurred handwritten journal page or note texture in warm low light. "
            f"The {text_zone} side contains one crisp highlighted truth moment and a clean zone for text while the {visual_zone} side stays soft and out of focus."
        ),
        "digital_anxiety_overlay": (
            f"The {visual_zone} half shows a person in a dark bedroom or apartment lit only by a phone screen, with the exact physical feeling of waiting for a reply that will not come. "
            "A realistic message or read-receipt anxiety moment is visible in the scene. "
            f"The {text_zone} half stays darker and cleaner for the text block."
        ),
        "dichotomy_split": (
            "The image is divided into a clean 50/50 vertical split with a thin warm terracotta dividing line. "
            f"On the {visual_zone} side the subject is in the problem state with cool muted tones, shadow, and tension. "
            f"On the {text_zone} side the resolution state is calmer, warmer, and more open with negative space preserved for text."
        ),
        "subject_vs_the_void": (
            "About 80 to 90 percent of the frame is imposing negative space in a vast dark environment. "
            f"A tiny human silhouette sits or stands low in the {visual_zone} area, dwarfed by the environment. "
            f"The upper {text_zone} area is a clean dark field for typography."
        ),
    }
    mood = {
        "A": "introspective and premium",
        "B": "raw and emotionally immediate",
        "C": "counter-intuitive and quietly intense",
    }.get(variant.get("id"), "introspective")
    return (
        "A cinematic YouTube thumbnail image. Final upload quality. 1280x720 pixels. 16:9 horizontal ratio. "
        "No watermarks, no borders, no logos, no UI chrome. "
        f'The scene is about "{topic}". {prompt_by_pattern.get(pattern, prompt_by_pattern["clean_concept_close_up"])} '
        f'In the text zone, {text_style} text reads exactly "{thumb_text}" in {text_color} with a heavy black outline for maximum contrast and readability at mobile scale. '
        "No important elements in the bottom-right 15% of the frame. "
        "Overall color grading is moody and cinematic. Base palette is deep midnight navy (#1C1C2B), warm terracotta (#C4785A), and soft cream (#F5F0E8), with optional sage green (#7BAE8A) only as a tiny accent if needed. "
        "High contrast between all elements, clearly readable in grayscale. One dominant focal point. Maximum three elements total. "
        f"Mood is {mood}. Photorealistic cinematic quality. Editorial film still aesthetic."
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
        thumb_text = _sanitize_thumb_text(variant.get("thumbnail_text", ""))
        # Use AI-authored visual prompt if present; otherwise build from pattern library
        prompt = str(variant.get("visual_prompt", "")).strip() or _build_generation_prompt(research, variant)
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
        _draw_text_overlay(output_path, thumb_text, variant_id, width, height)

        raw_generated = (
            generated_path if source == "pollinations_gptimage" else
            gemini_generated_path if source == "gemini_imagen" else
            frame_path if os.path.exists(frame_path) else ""
        )
        generated_variants.append({
            "id": variant_id,
            "angle": variant.get("angle", ""),
            "pattern": variant.get("pattern", ""),
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


run_longform_thumbnail_mock = run_longform_thumbnail
