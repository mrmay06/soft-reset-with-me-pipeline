from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional
from PIL import Image, ImageDraw, ImageFont, ImageStat  # noqa: F401

from utils.helpers import load_json, save_json, now_iso

MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024

COLORS = {
    "background": "#0D0D0D",
    "headline_text": "#F0EBE0",
    "secondary_text": "#C4785A",
    "accent_line": "#C4785A",
    "text_outline": "#000000",
    "split_divider": "#C4785A",
}

SAFE_ZONE = {
    "padding_top": 108,
    "padding_bottom": 216,
    "padding_left": 108,
    "padding_right": 108,
    "danger_bottom_right_x": 1536,
    "danger_bottom_y": 864,
    "danger_bottom_left_x": 288,
}

STRUCTURE_BY_VARIANT = {
    "A": "typography",
    "B": "face_text",
    "C": "split",
}


def _extract_frame(video_path: str, output_path: str, at_sec: float):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_sec), "-i", video_path, "-vframes", "1", "-q:v", "2", output_path],
        check=True,
        capture_output=True,
    )


def _resize_to_target(path_in: str, path_out: str, width: int, height: int):
    image = Image.open(path_in).convert("RGB")
    source_ratio = image.width / image.height
    target_ratio = width / height
    if source_ratio > target_ratio:
        crop_width = int(image.height * target_ratio)
        left = (image.width - crop_width) // 2
        image = image.crop((left, 0, left + crop_width, image.height))
    else:
        crop_height = int(image.width / target_ratio)
        top = (image.height - crop_height) // 2
        image = image.crop((0, top, image.width, top + crop_height))
    image = image.resize((width, height), Image.LANCZOS)
    image.save(path_out)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _add_grain(image: Image.Image, opacity: float = 0.04) -> Image.Image:
    """Add deterministic film grain without pulling in numpy."""
    image = image.convert("RGB")
    grain = Image.effect_noise(image.size, 18).convert("L")
    grain_rgb = Image.merge("RGB", (grain, grain, grain))
    return Image.blend(image, grain_rgb, opacity)


def _save_png_under_limit(image: Image.Image, output_path: str) -> bool:
    image.save(output_path, optimize=True)
    if os.path.getsize(output_path) <= MAX_THUMBNAIL_BYTES:
        return False
    # YouTube thumbnails must be under 2MB. Adaptive PNG quantization keeps the
    # existing .png upload path while avoiding oversized photorealistic renders.
    for colors in (256, 192, 128, 96, 64):
        quantized = image.convert("P", palette=Image.ADAPTIVE, colors=colors)
        quantized.save(output_path, optimize=True)
        if os.path.getsize(output_path) <= MAX_THUMBNAIL_BYTES:
            return True
    return False


def _sanitize_thumb_text(text: str, max_words: int = 5, uppercase: bool = True, max_chars: int | None = None) -> str:
    """Normalize to ASCII-safe thumbnail copy."""
    replacements = {"≠": "!=", "→": ">", "—": "-", "–": "-", "'": "'", "'": "'",
                    "“": '"', "”": '"', "…": "...", "é": "e", "è": "e"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.encode("ascii", errors="ignore").decode("ascii")
    text = " ".join(text.split())
    words = text.split()
    cleaned = " ".join(words[:max_words]).strip()
    cleaned = cleaned.upper() if uppercase else cleaned.lower()
    if max_chars and len(cleaned) > max_chars:
        clipped = cleaned[:max_chars].rsplit(" ", 1)[0].strip()
        cleaned = clipped or cleaned[:max_chars].strip()
    return cleaned


def _variant_copy(variant: dict) -> tuple[str, str, str]:
    line1 = _sanitize_thumb_text(variant.get("line1", ""), max_words=4, uppercase=True, max_chars=18)
    line2 = _sanitize_thumb_text(variant.get("line2", ""), max_words=7, uppercase=False, max_chars=35)
    if not line1:
        legacy = _sanitize_thumb_text(variant.get("thumbnail_text", ""), max_words=4, uppercase=True, max_chars=18)
        line1 = legacy or "YOU ALREADY KNOW"
    if not line2:
        line2 = "this is why it hurts"
    combined = f"{line1} / {line2}"
    return line1, line2, combined


def _font(font_path: str, size: int):
    try:
        return ImageFont.truetype(font_path, size=size)  # noqa: F821
    except Exception:
        return ImageFont.load_default()  # noqa: F821


def _fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: str, start_size: int, max_width: int, min_size: int, stroke_width: int = 0):
    size = max(start_size, min_size)
    while size >= min_size:
        font = _font(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
        if bbox[2] - bbox[0] <= max_width:
            return font, size
        size -= 4
    return font, size


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, stroke_width: int = 0) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=stroke_width)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines[:2]


def _text_block_size(draw: ImageDraw.ImageDraw, lines: list[str], font, line_gap: int, stroke_width: int = 0) -> tuple[int, int]:
    widths = []
    heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        widths.append(bbox[2] - bbox[0])
        heights.append(bbox[3] - bbox[1])
    return (max(widths or [0]), sum(heights) + max(0, len(lines) - 1) * line_gap)


def _draw_typography_thumbnail(output_path: str, line1: str, line2: str, width: int, height: int) -> None:
    img = Image.new("RGB", (width, height), _hex_to_rgb(COLORS["background"]))
    img = _add_grain(img, 0.045)
    draw = ImageDraw.Draw(img)  # noqa: F821
    serif = "assets/fonts/DMSerifDisplay-Regular.ttf"
    sans = "assets/fonts/Inter-Bold.ttf"
    headline_fill = _hex_to_rgb(COLORS["headline_text"])
    terracotta = _hex_to_rgb(COLORS["accent_line"])
    outline = _hex_to_rgb(COLORS["text_outline"])
    max_width = width - SAFE_ZONE["padding_left"] - SAFE_ZONE["padding_right"]
    stroke = 6 if width >= 1920 else 4
    headline_font, headline_size = _fit_font(
        draw, line1, serif, int(height * 0.13), max_width, int(height * 0.07), stroke
    )
    headline_lines = _wrap_text(draw, line1, headline_font, max_width, stroke)
    line_gap = int(headline_size * 0.10)
    block_w, block_h = _text_block_size(draw, headline_lines, headline_font, line_gap, stroke)
    headline_y = int(height * 0.42) - block_h // 2
    for idx, line in enumerate(headline_lines):
        bbox = draw.textbbox((0, 0), line, font=headline_font, stroke_width=stroke)
        x = (width - (bbox[2] - bbox[0])) // 2
        y = headline_y + idx * (headline_size + line_gap)
        draw.text((x, y), line, font=headline_font, fill=headline_fill, stroke_width=stroke, stroke_fill=outline)
    separator_y = headline_y + block_h + 40
    line_width = min(1200, int(width * 0.625))
    draw.line(((width - line_width) // 2, separator_y, (width + line_width) // 2, separator_y), fill=terracotta, width=3)
    secondary_font, _ = _fit_font(draw, line2, sans, int(height * 0.042), 1400, int(height * 0.032))
    sec_bbox = draw.textbbox((0, 0), line2, font=secondary_font)
    draw.text(((width - (sec_bbox[2] - sec_bbox[0])) // 2, separator_y + 30), line2, font=secondary_font, fill=terracotta)
    compressed = _save_png_under_limit(img, output_path)
    if compressed:
        print("[longform_thumbnail] Typography thumbnail PNG optimized under 2MB")


def _draw_face_text_overlay(image_path: str, line1: str, line2: str, width: int, height: int) -> None:
    img = Image.open(image_path).convert("RGB")
    img = _add_grain(img, 0.025)
    # Guarantee legibility even when the selected source frame has a bright
    # left side. Keep the subject side untouched.
    scrim = Image.new("RGBA", img.size, (0, 0, 0, 0))
    scrim_draw = ImageDraw.Draw(scrim)
    scrim_draw.rectangle((0, 0, int(width * 0.50), height), fill=(0, 0, 0, 150))
    img = Image.alpha_composite(img.convert("RGBA"), scrim).convert("RGB")
    draw = ImageDraw.Draw(img)  # noqa: F821
    serif = "assets/fonts/DMSerifDisplay-Regular.ttf"
    sans = "assets/fonts/Inter-Bold.ttf"
    headline_fill = _hex_to_rgb(COLORS["headline_text"])
    secondary_fill = _hex_to_rgb(COLORS["secondary_text"])
    outline = _hex_to_rgb(COLORS["text_outline"])
    left = SAFE_ZONE["padding_left"]
    top = SAFE_ZONE["padding_top"]
    max_width = int(width * 0.42) - left
    stroke = 6 if width >= 1920 else 4
    line1_font, line1_size = _fit_font(draw, line1, serif, int(height * 0.166), max_width, int(height * 0.08), stroke)
    line2_font, _ = _fit_font(draw, line2, sans, int(height * 0.048), max_width, int(height * 0.034))
    draw.text((left, top), line1, font=line1_font, fill=headline_fill, stroke_width=stroke, stroke_fill=outline)
    line1_box = draw.textbbox((left, top), line1, font=line1_font, stroke_width=stroke)
    line2_y = line1_box[3] + 36
    draw.text((left, line2_y), line2, font=line2_font, fill=secondary_fill)
    compressed = _save_png_under_limit(img, image_path)
    if compressed:
        print("[longform_thumbnail] Face/text thumbnail PNG optimized under 2MB")


def _draw_split_overlay(image_path: str, line1: str, line2: str, width: int, height: int) -> None:
    img = Image.open(image_path).convert("RGB")
    img = _add_grain(img, 0.025)
    draw = ImageDraw.Draw(img)  # noqa: F821
    serif = "assets/fonts/DMSerifDisplay-Regular.ttf"
    sans = "assets/fonts/Inter-Bold.ttf"
    headline_fill = _hex_to_rgb(COLORS["headline_text"])
    terracotta = _hex_to_rgb(COLORS["secondary_text"])
    outline = _hex_to_rgb(COLORS["text_outline"])
    divider_x = width // 2
    draw.line((divider_x, 0, divider_x, height), fill=terracotta, width=6)
    top_scrim = Image.new("RGBA", img.size, (0, 0, 0, 0))
    top_draw = ImageDraw.Draw(top_scrim)
    top_draw.rectangle((0, 0, width, int(height * 0.28)), fill=(0, 0, 0, 145))
    img = Image.alpha_composite(img.convert("RGBA"), top_scrim).convert("RGB")
    draw = ImageDraw.Draw(img)
    headline_font, _ = _fit_font(draw, line1, serif, int(height * 0.105), int(width * 0.80), int(height * 0.06), 4)
    headline_box = draw.textbbox((0, 0), line1, font=headline_font, stroke_width=4)
    headline_x = (width - (headline_box[2] - headline_box[0])) // 2
    draw.text((headline_x, SAFE_ZONE["padding_top"]), line1, font=headline_font, fill=headline_fill, stroke_width=4, stroke_fill=outline)
    secondary = line2 or line1
    secondary_font, _ = _fit_font(draw, secondary, sans, int(height * 0.052), width - 216, int(height * 0.036))
    sec_bbox = draw.textbbox((0, 0), secondary, font=secondary_font)
    sec_x = (width - (sec_bbox[2] - sec_bbox[0])) // 2
    sec_y = SAFE_ZONE["danger_bottom_y"] - (sec_bbox[3] - sec_bbox[1]) - 10
    draw.text((sec_x, sec_y), secondary, font=secondary_font, fill=terracotta)
    compressed = _save_png_under_limit(img, image_path)
    if compressed:
        print("[longform_thumbnail] Split thumbnail PNG optimized under 2MB")


def _draw_text_overlay(image_path: str, line1: str, line2: str, variant_id: str, width: int, height: int, structure: str) -> None:
    """Bake exact thumbnail text with PIL so AI image text never leaks in."""
    if not line1 and not line2:
        return
    if structure == "typography":
        _draw_typography_thumbnail(image_path, line1, line2, width, height)
    elif structure == "split":
        _draw_split_overlay(image_path, line1, line2, width, height)
    else:
        _draw_face_text_overlay(image_path, line1, line2, width, height)
    print(f"[longform_thumbnail] Text overlay applied: '{line1}' / '{line2}' (variant {variant_id}, {structure})")


def _variant_structure(variant: dict) -> str:
    raw = str(variant.get("structure") or variant.get("pattern") or "").lower().strip()
    if raw in {"typography", "pure_typography", "text_only"}:
        return "typography"
    if raw in {"split", "split_screen", "before_after", "two_plate_composite"}:
        return "split"
    if raw in {"face_text", "one_face_right_negative_space_left", "face_right_text_left"}:
        return "face_text"
    variant_id = str(variant.get("id", "")).upper()
    return STRUCTURE_BY_VARIANT.get(variant_id, "face_text")


def _base_prompt() -> str:
    return (
        "A photorealistic cinematic YouTube thumbnail background with NO TEXT. "
        "1920x1080 pixels, 16:9 horizontal, final upload quality. "
        "No watermarks, no borders, no logos, no UI chrome. "
        "Minimum 108 pixel padding from every edge. "
        "No important elements in the bottom-right 20 percent or bottom-left 15 percent of the frame. "
        "Cool-neutral color grade, slightly desaturated, subtle film grain, no warm amber or orange lighting. "
    )


def _build_typography_prompt(research: dict, variant: dict) -> str:
    line1, line2, _ = _variant_copy(variant)
    topic = str(research.get("topic", "") or "relationship healing").strip()
    return (
        _base_prompt()
        + f"Pure typography structure for emotional relationship content about {topic}. "
        f"Deep near-black charcoal background {COLORS['background']} with subtle film grain texture. "
        f"Large heavy editorial serif headline will read exactly '{line1}' in warm off-white cream {COLORS['headline_text']}. "
        f"A thin terracotta separator line {COLORS['accent_line']} sits below the headline. "
        f"Smaller bold sans-serif secondary text will read exactly '{line2}' in muted terracotta {COLORS['secondary_text']}. "
        "Premium editorial book-cover quality. No photography, no icons, no extra elements."
    )


def _build_face_text_prompt(research: dict, variant: dict) -> str:
    topic = str(research.get("topic", "") or "relationship healing").strip()
    visual_context = str(variant.get("visual_prompt", "") or "").strip()
    portrait_scene = str(variant.get("portrait_scene", "") or visual_context).strip()
    gender = str(variant.get("subject_gender", "") or "person").strip()
    mood = {
        "A": "introspective and premium",
        "B": "raw and emotionally immediate",
        "C": "counter-intuitive and quietly intense",
    }.get(variant.get("id"), "introspective")
    return (
        _base_prompt()
        + "Face-right text-left structure. One young adult face in close-up fills the right 58 percent of the frame. "
        "The left 42 percent is clean dark charcoal negative space for text, completely empty. "
        f"Subject: {gender}, mid-twenties to early thirties. "
        "Expression: quiet devastated recognition, heavy eyes, gaze slightly toward the left text zone, lips softly parted or gently closed. "
        "No smile, no open-mouth shock, no obvious crying, no performed drama. "
        "Camera at eye level or slightly below eye level. Tight crop: face and upper shoulder only. "
        "Loose natural slightly disheveled hair, simple dark or neutral clothing with no logos and no patterns. "
        "Lighting: soft diffused cool-neutral daylight from a large overcast window. "
        "Do not use warm amber light, golden hour, candlelight, orange tones, teal tones, or blue-green color cast. "
        "Background: completely out-of-focus neutral dark gray, no identifiable location, no sharp objects, no text, no UI. "
        "Natural skin texture with visible pores, subtle film grain, slightly desaturated prestige drama color grade. "
        "Maximum three visual elements total: face, background, empty text zone. "
        f'The emotional context is "{topic}". Mood is {mood}. '
        f"Additional visual context to translate subtly without adding objects or text: {portrait_scene}"
    )


def _build_split_plate_prompt(research: dict, variant: dict, side: str) -> str:
    topic = str(research.get("topic", "") or "relationship healing").strip()
    scene_key = "scene_left" if side == "left" else "scene_right"
    fallback_scene = (
        "the unresolved problem state, cold dark and emotionally tense"
        if side == "left"
        else "the resolution state, clearer and steady but not overly happy"
    )
    scene = str(variant.get(scene_key, "") or fallback_scene).strip()
    tone = "cold dark blue-gray, desaturated, emotionally tense" if side == "left" else "cool-neutral, slightly lighter, calm clarity"
    return (
        "Generate one half of a 1920x1080 cinematic YouTube thumbnail background with NO TEXT. "
        "Output should be 960x1080, vertical half-frame plate. "
        f"This is the {side} plate of a split-screen before/after thumbnail about {topic}. "
        f"Scene: {scene}. Tone: {tone}. "
        "No warm amber, orange, golden hour, logos, UI chrome, text, or sharp distracting objects. "
        "Photorealistic prestige drama still, out-of-focus environment, subtle grain."
    )


def _build_split_prompt(research: dict, variant: dict) -> str:
    topic = str(research.get("topic", "") or "relationship healing").strip()
    return (
        _base_prompt()
        + f"Split-screen two-plate composite for emotional relationship content about {topic}. "
        "Left half shows the cold unresolved problem state. Right half shows cool-neutral clarity and resolution. "
        "A muted terracotta divider will be added in post. Generated image must contain no text."
    )


def _build_generation_prompt(research: dict, variant: dict, structure: str) -> str:
    if structure == "typography":
        return _build_typography_prompt(research, variant)
    if structure == "split":
        return _build_split_prompt(research, variant)
    return _build_face_text_prompt(research, variant)


def _create_typography_base(output_path: str, width: int, height: int) -> str:
    image = Image.new("RGB", (width, height), _hex_to_rgb(COLORS["background"]))
    image = _add_grain(image, 0.045)
    _save_png_under_limit(image, output_path)
    return "local_typography"


def _frame_score(path: str) -> float:
    image = Image.open(path).convert("L").resize((320, 180))
    stat = ImageStat.Stat(image)
    contrast = float(stat.stddev[0])
    mean = float(stat.mean[0])
    exposure = max(0.0, 45.0 - abs(mean - 115.0) * 0.25)
    return contrast + exposure


def _extract_ranked_source_frames(render_meta: dict, run_dir: str) -> list[dict]:
    """Extract clean frames from source clips, before captions are burned in."""
    frames = []
    for index, asset in enumerate(render_meta.get("visual_assets", [])):
        relative = str(asset.get("path", ""))
        source_path = os.path.join(run_dir, relative)
        if not relative or not os.path.exists(source_path):
            continue
        path = os.path.join(run_dir, f"07_longform_source_frame_{index:02d}.jpg")
        _extract_frame(source_path, path, 1.0)
        query = str(asset.get("query", "")).lower()
        frames.append({"path": path, "query": query, "score": _frame_score(path)})
    if len(frames) < 2:
        raise RuntimeError("Footage-derived thumbnails require at least two clean source clips")
    return sorted(frames, key=lambda item: item["score"], reverse=True)


def _pick_thumbnail_frames(frames: list[dict]) -> tuple[str, str, str]:
    people_terms = ("person", "woman", "man", "people", "couple", "face")
    tension_terms = ("alone", "rain", "night", "phone", "empty")
    release_terms = ("morning", "open", "calm", "walk", "curtains")

    def best_with(terms: tuple[str, ...], excluded: Optional[set[str]] = None) -> dict:
        excluded = excluded or set()
        matching = [
            item for item in frames
            if item["path"] not in excluded and any(term in item["query"] for term in terms)
        ]
        return (matching or [item for item in frames if item["path"] not in excluded])[0]

    face = best_with(people_terms)
    left = best_with(tension_terms)
    right = best_with(release_terms, {left["path"]})
    return face["path"], left["path"], right["path"]


def _build_edit_brief(research: dict, variant: dict, structure: str) -> str:
    line1, line2, _ = _variant_copy(variant)
    topic = str(research.get("topic", "relationship healing"))
    common = (
        "Use only a clean frame extracted from this video's original stock clips. "
        "Do not generate imagery and do not use a frame containing captions, logos, UI, or watermarks. "
        "Preserve photographic realism; only crop, grade, darken, and add local typography."
    )
    if structure == "typography":
        return (
            f"LOCAL TYPOGRAPHY THUMBNAIL for: {topic}. {common} "
            f"Use a deep charcoal field with subtle grain. Headline: '{line1}'. Supporting line: '{line2}'. "
            "Keep the hierarchy readable at phone size and leave the bottom-right timestamp area empty."
        )
    if structure == "split":
        return (
            f"TWO-SOURCE-FRAME SPLIT THUMBNAIL for: {topic}. {common} "
            "Choose two visually distinct source frames that communicate tension and release without claiming a literal before/after. "
            f"Headline: '{line1}'. Supporting line: '{line2}'. Use one restrained divider."
        )
    return (
        f"SINGLE-SOURCE-FRAME THUMBNAIL for: {topic}. {common} "
        "Prefer a clear emotional subject with usable negative space on the left; if unavailable, choose the strongest uncluttered frame. "
        f"Headline: '{line1}'. Supporting line: '{line2}'."
    )


def _create_split_from_frames(left_path: str, right_path: str, output_path: str, width: int, height: int) -> None:
    plate_width = width // 2
    temp_left = output_path + ".left.png"
    temp_right = output_path + ".right.png"
    _resize_to_target(left_path, temp_left, plate_width, height)
    _resize_to_target(right_path, temp_right, width - plate_width, height)
    composite = Image.new("RGB", (width, height), _hex_to_rgb(COLORS["background"]))
    composite.paste(Image.open(temp_left).convert("RGB"), (0, 0))
    composite.paste(Image.open(temp_right).convert("RGB"), (plate_width, 0))
    _save_png_under_limit(composite, output_path)
    os.remove(temp_left)
    os.remove(temp_right)


def run_longform_thumbnail(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[longform_thumbnail] Creating footage-derived A/B/C thumbnails for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    render_meta = load_json(os.path.join(run_dir, "06_longform_render_meta.json"))
    video_path = os.path.join(run_dir, "06_longform_video.mp4")
    width = int(config.get("longform_thumbnail_width", 1280))
    height = int(config.get("longform_thumbnail_height", 720))
    primary_id = str(metadata.get("primary_variant_id", "B")).upper()
    ranked_frames = _extract_ranked_source_frames(render_meta, run_dir)
    face_frame, split_left_frame, split_right_frame = _pick_thumbnail_frames(ranked_frames)

    generated_variants = []
    for variant in metadata.get("thumbnail_variants", []):
        variant_id = str(variant.get("id", "")).upper()
        if variant_id not in {"A", "B", "C"}:
            continue
        line1, line2, thumb_text = _variant_copy(variant)
        structure = _variant_structure(variant)
        prompt = _build_edit_brief(research, variant, structure)
        prompt_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}_prompt.txt")
        output_path = os.path.join(run_dir, f"07_longform_thumbnail_{variant_id}.png")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt)

        if structure == "typography":
            source = _create_typography_base(output_path, width, height)
        elif structure == "split":
            _create_split_from_frames(split_left_frame, split_right_frame, output_path, width, height)
            source = "two_footage_frames"
        else:
            _resize_to_target(face_frame, output_path, width, height)
            source = "ranked_footage_frame"

        # Always bake text via PIL — guarantees legibility regardless of image source
        _draw_text_overlay(output_path, line1, line2, variant_id, width, height, structure)

        generated_variants.append({
            "id": variant_id,
            "angle": variant.get("angle", ""),
            "pattern": variant.get("pattern", ""),
            "structure": structure,
            "line1": line1,
            "line2": line2,
            "thumbnail_text": thumb_text,
            "prompt_file": os.path.basename(prompt_path),
            "generated_file": "",
            "output_file": os.path.basename(output_path),
            "background_source": source,
            "final_output_size": f"{width}x{height}",
            "degraded_fallback": False,
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
        "thumbnail_strategy": "footage_derived_ab_packaging_v3",
        "generated_images_used": False,
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
        structure = _variant_structure(variant)
        output_file = f"07_longform_thumbnail_{variant_id}.png"
        output_path = os.path.join(run_dir, output_file)
        image = Image.new("RGB", (width, height), _hex_to_rgb(COLORS["background"]))
        draw = ImageDraw.Draw(image)
        if structure == "face_text":
            draw.rectangle((int(width * 0.42), 0, width, height), fill=(42, 42, 42))
        elif structure == "split":
            draw.rectangle((0, 0, width // 2, height), fill=(22, 25, 30))
            draw.rectangle((width // 2, 0, width, height), fill=(44, 46, 47))
        image = _add_grain(image, 0.045)
        _save_png_under_limit(image, output_path)
        line1, line2, thumb_text = _variant_copy(variant)
        _draw_text_overlay(output_path, line1, line2, variant_id, width, height, structure)
        generated_variants.append({
            "id": variant_id,
            "angle": variant.get("angle", "mock"),
            "pattern": variant.get("pattern", "mock"),
            "structure": structure,
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
