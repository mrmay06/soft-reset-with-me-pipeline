from __future__ import annotations

import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.helpers import load_json


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _clean_text(text: str) -> str:
    text = str(text or "").replace("—", " ").replace("–", " ").replace("--", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _thumbnail_text(metadata: dict, research: dict) -> str:
    raw = _clean_text(metadata.get("thumbnail_text", ""))
    topic = _clean_text(research.get("topic", "")).lower()
    if "potential" in topic or "imagined" in topic:
        raw = "YOU MISS THE DREAM"
    elif "peace" in topic or "chaos" in topic:
        raw = "WHY CALM FEELS WRONG"
    elif "strong one" in topic:
        raw = "TIRED OF BEING STRONG"
    elif not raw:
        raw = _clean_text(metadata.get("title", "SOFT RESET"))
    words = raw.upper().split()
    return " ".join(words[:5]) or "SOFT RESET"


def _extract_frame(video_path: str, output_path: str, at_sec: float):
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(at_sec), "-i", video_path, "-vframes", "1", "-q:v", "2", output_path],
        check=True,
        capture_output=True,
    )


def _cover_resize(img: Image.Image, width: int, height: int) -> Image.Image:
    scale = max(width / img.width, height / img.height)
    resized = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font, stroke_width=4)
        if bbox[2] - bbox[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


def _draw_text(image: Image.Image, text: str) -> Image.Image:
    draw = ImageDraw.Draw(image)
    cream = (245, 240, 232)
    terracotta = (196, 120, 90)
    midnight = (28, 28, 43)
    dm = _font("assets/fonts/DMSerifDisplay-Regular.ttf", 92)
    inter = _font("assets/fonts/Inter-Bold.ttf", 24)
    lines = _wrap(draw, text, dm, 650)
    line_height = 102
    y = 145
    for line_idx, line in enumerate(lines):
        words = line.split()
        accent_last = line_idx == len(lines) - 1
        if not accent_last:
            draw.text((74, y), line, font=dm, fill=cream, stroke_width=5, stroke_fill=midnight)
        else:
            if len(words) == 1:
                draw.text((74, y), line, font=dm, fill=terracotta, stroke_width=5, stroke_fill=midnight)
            else:
                white = " ".join(words[:-1]) + " "
                accent = words[-1]
                draw.text((74, y), white, font=dm, fill=cream, stroke_width=5, stroke_fill=midnight)
                white_w = draw.textbbox((0, 0), white, font=dm, stroke_width=5)[2]
                draw.text((74 + white_w, y), accent, font=dm, fill=terracotta, stroke_width=5, stroke_fill=midnight)
        y += line_height
    draw.text((78, 624), "SOFT RESET WITH ME", font=inter, fill=terracotta)
    return image


def run_longform_thumbnail(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[longform_thumbnail] Creating thumbnail for {video_id}")
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    render_meta = load_json(os.path.join(run_dir, "06_longform_render_meta.json"))
    video_path = os.path.join(run_dir, "06_longform_video.mp4")
    frame_path = os.path.join(run_dir, "07_longform_thumbnail_frame.jpg")
    output_path = os.path.join(run_dir, "07_longform_thumbnail.png")

    duration = float(render_meta.get("duration_sec", 300))
    _extract_frame(video_path, frame_path, at_sec=max(8, duration * 0.18))
    base = Image.open(frame_path).convert("RGB")
    width = int(config.get("longform_thumbnail_width", 1280))
    height = int(config.get("longform_thumbnail_height", 720))
    base = _cover_resize(base, width, height)

    blurred = base.filter(ImageFilter.GaussianBlur(radius=5)).convert("RGBA")
    dark = Image.new("RGBA", (width, height), (0, 0, 0, 86))
    left_scrim = Image.new("RGBA", (width, height), (28, 28, 43, 0))
    scrim_px = left_scrim.load()
    for x in range(width):
        alpha = max(0, int(205 * (1 - x / (width * 0.82))))
        for y in range(height):
            scrim_px[x, y] = (28, 28, 43, alpha)
    image = Image.alpha_composite(Image.alpha_composite(blurred, dark), left_scrim).convert("RGB")
    image = _draw_text(image, _thumbnail_text(metadata, research))
    image.save(output_path)
    print(f"[longform_thumbnail] Done. Output: {output_path}")
    return output_path


run_longform_thumbnail_mock = run_longform_thumbnail
