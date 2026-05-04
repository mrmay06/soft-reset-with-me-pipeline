import os
import subprocess
import textwrap

from utils.helpers import load_json, now_iso

try:
    from PIL import Image, ImageFilter, ImageDraw, ImageFont
except ImportError:
    Image = None


def _prepare_base_image(asset_meta: dict, run_dir: str) -> "Image.Image":
    images_dir = os.path.join(run_dir, "03_images")

    # Prefer AI-generated thumbnail image from visual director
    ai_thumb = os.path.join(images_dir, "thumbnail.png")
    if os.path.exists(ai_thumb):
        base = Image.open(ai_thumb).convert("RGB")
        if base.size != (1080, 1920):
            base = base.resize((1080, 1920), Image.LANCZOS)
        return base

    # Fallback: use the first generated scene asset.
    assets = asset_meta.get("assets", {})
    first_key = "scene_1" if "scene_1" in assets else None
    if first_key:
        asset = assets[first_key]
        if asset["type"] == "video":
            frame_path = os.path.join(images_dir, "thumb_frame.png")
            video_path = os.path.join(run_dir, asset["path"])
            try:
                subprocess.run(
                    ["ffmpeg", "-i", video_path, "-vframes", "1", "-q:v", "2", frame_path, "-y"],
                    check=True, capture_output=True
                )
                base = Image.open(frame_path).convert("RGB")
            except Exception as e:
                print(f"[thumbnail] FFmpeg frame extract failed ({e}) — gradient fallback")
                base = _make_gradient_fallback()
        else:
            img_path = os.path.join(run_dir, asset["path"])
            base = Image.open(img_path).convert("RGB")
        if base.size != (1080, 1920):
            base = base.resize((1080, 1920), Image.LANCZOS)
        return base

    print("[thumbnail] No base image found — using gradient fallback")
    return _make_gradient_fallback()


def _make_gradient_fallback() -> "Image.Image":
    img = Image.new("RGB", (1080, 1920), (10, 10, 10))  # StackNote #0A0A0A
    return img


def _apply_background_treatment(base: "Image.Image") -> "Image.Image":
    blurred = base.filter(ImageFilter.GaussianBlur(radius=18))
    overlay = Image.new("RGBA", blurred.size, (0, 0, 0, 100))
    blurred_rgba = blurred.convert("RGBA")
    combined = Image.alpha_composite(blurred_rgba, overlay)
    return combined.convert("RGB")


def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]  # max 2 lines


def _draw_thumbnail_text(image: "Image.Image", thumbnail_text: str) -> "Image.Image":
    """
    StackNote brand: white text, last word in green (#3DBE29), black stroke.
    Rule: never more than one green word per frame.
    """
    draw = ImageDraw.Draw(image)

    font_path = "assets/fonts/Anton-Regular.ttf"
    try:
        font = ImageFont.truetype(font_path, size=110)
    except Exception:
        print("[thumbnail] Anton-Regular.ttf not found — falling back to Inter-Bold")
        try:
            font = ImageFont.truetype("assets/fonts/Inter-Bold.ttf", size=110)
        except Exception:
            font = ImageFont.load_default()

    lines = _wrap_text(thumbnail_text, font, max_width=900, draw=draw)

    # StackNote accent: the last word of the last line gets green
    GREEN = (57, 181, 74)   # #39B54A
    WHITE = (255, 255, 255)

    line_height = 130
    total_height = len(lines) * line_height
    y = (1920 - total_height) // 2

    for line_idx, line in enumerate(lines):
        words = line.split()
        is_last_line = (line_idx == len(lines) - 1)

        # For non-last lines, render the whole line in white
        if not is_last_line or len(words) <= 1:
            bbox = draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x = (1080 - text_width) // 2
            color = GREEN if (is_last_line and len(words) == 1) else WHITE
            draw.text((x, y), line, font=font, fill=color)
        else:
            # Last line: white words except the last one which is green
            white_part = " ".join(words[:-1]) + " "
            green_word = words[-1]

            # Measure the full line to center it
            full_bbox = draw.textbbox((0, 0), line, font=font)
            total_w = full_bbox[2] - full_bbox[0]
            x_start = (1080 - total_w) // 2

            # White portion
            white_bbox = draw.textbbox((0, 0), white_part, font=font)
            white_w = white_bbox[2] - white_bbox[0]
            draw.text((x_start, y), white_part, font=font, fill=WHITE)

            # Green word
            x_green = x_start + white_w
            draw.text((x_green, y), green_word, font=font, fill=GREEN)

        y += line_height

    return image


def run_thumbnail(video_id: str, run_dir: str, config: dict) -> str:
    print(f"[thumbnail] Creating thumbnail for {video_id}")

    if Image is None:
        raise RuntimeError("Pillow not installed")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    asset_meta = load_json(os.path.join(run_dir, "03_asset_meta.json"))
    output_path = os.path.join(run_dir, "05_thumbnail.png")

    base = _prepare_base_image(asset_meta, run_dir)
    base = _apply_background_treatment(base)
    thumbnail_text = script.get("thumbnail_text", script["hook"][:24])
    base = _draw_thumbnail_text(base, thumbnail_text)
    base.save(output_path)

    print(f"[thumbnail] Done. Text: '{thumbnail_text}'")
    return output_path


# Mock is identical to real — no API calls needed, just PIL
run_thumbnail_mock = run_thumbnail
