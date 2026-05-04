from __future__ import annotations
import os
import time
import random
import re
import hashlib
import urllib.parse

import requests

from utils.helpers import load_json, save_json, now_iso
from utils.gemini_client import generate_text
from utils.retry import retry

try:
    from PIL import Image
    import io
except ImportError:
    Image = None
    io = None

# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_pexels_query(prompt: str, config: dict) -> str:
    """Distil a Pollinations prompt into a short Pexels search query via Gemini."""
    fallback = _heuristic_stock_query(prompt)
    if config.get("stock_images_fallback_only") or config.get("prefer_stock_images"):
        return fallback
    try:
        return _sanitize_stock_query(generate_text(
            f"Extract a 3-5 word Pexels stock search query from this image description. "
            f"Never include anime, cartoon, mascot, chibi, animal, or furry character terms. "
            f"Use moody stock terms like rainy apartment window, city night walking, candlelit bedroom, hands closing journal, empty chair room, hallway night, phone face down, or train window night. "
            f"Return only the search terms, nothing else.\n\nDescription: {prompt}",
            config.get("research_model", "gemini-2.5-flash"),
        ).lower())
    except Exception:
        return fallback


def _heuristic_stock_query(prompt: str) -> str:
    text = (prompt or "").lower()
    if "door handle" in text or "door" in text:
        return "hand on door handle"
    if "hallway" in text:
        return "hallway night"
    if "leaving" in text or "leave" in text:
        return "person leaving room"
    if "empty chair" in text or "chair" in text:
        return "empty chair room"
    if "phone" in text:
        return "phone face down"
    if "journal" in text or "notebook" in text:
        return "hands closing journal"
    if "candle" in text or "lamp" in text:
        return "candlelit room"
    if "city" in text or "walking" in text:
        return "city night walking"
    if "rain" in text or "window" in text:
        return "rainy apartment window"
    return _sanitize_stock_query(" ".join((prompt or "").split()[:4]))


def _sanitize_stock_query(query: str) -> str:
    cleaned = re.sub(
        r"\b(raccoons?|animals?|wildlife|cartoons?|mascots?|chibi|furry|fur|creature|anime)\b",
        "person",
        query,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned or "candlelit bedroom"


def _video_query_alternates(query: str) -> list[str]:
    """Keep API searches related, but broad enough for smaller stock libraries."""
    base = _sanitize_stock_query(query)
    text = f" {base} "
    alternates = [base]
    if any(token in text for token in (" phone ", " text ", " texting ", " dm ", " message ", " reply ")):
        alternates.extend(["phone", "texting", "smartphone"])
    if any(token in text for token in (" rain ", " rainy ", " window ")):
        alternates.extend(["rainy window", "window rain", "rain"])
    if any(token in text for token in (" candle ", " candlelit ", " candlelight ")):
        alternates.extend(["candle", "candlelight", "room"])
    if any(token in text for token in (" city ", " walking ", " street ")):
        alternates.extend(["city night", "walking city", "person walking"])
    if any(token in text for token in (" journal ", " writing ", " book ", " pages ")):
        alternates.extend(["book", "writing", "journal"])
    if any(token in text for token in (" chair ", " alone ", " room ")):
        alternates.extend(["empty chair", "alone room", "room"])
    if any(token in text for token in (" person ", " pensive ", " confused ", " looking ")):
        alternates.extend(["person alone", "person looking", "portrait"])

    deduped = []
    for item in alternates:
        item = _sanitize_stock_query(item)
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:5]


BRAND_STYLE_SUFFIX = (
    "moody editorial cinematic still, slightly desaturated warm tones, "
    "Deep Midnight base, Warm Terracotta practical light accent, "
    "real-world photographic scene only, continuous natural background surfaces, "
    "window glass, candlelight, furniture, closed journal, hands, and shadows only, "
    "unedited camera frame, no graphic overlay, no captions, no signage, no readable screens, intimate close-up, "
    "shallow depth of field, faceless composition, 9:16 vertical"
)


def _sanitize_prompt_for_text_artifacts(prompt: str) -> str:
    """Reduce prompt terms that make image models draw words or title-card blocks."""
    cleaned = prompt or ""
    replacements = {
        "Soft Cream negative space for later overlay": "natural dark cinematic background",
        "Deep Midnight background, Warm Terracotta accent": "Deep Midnight base, Warm Terracotta practical light accent",
        "large clean negative space for later overlay": "natural dark cinematic background",
        "natural uncluttered dark negative space for later overlay": "natural dark cinematic background",
        "natural dark negative space for later overlays": "natural dark cinematic background",
        "natural dark negative space for later overlay": "natural dark cinematic background",
        "negative space for later overlay": "natural dark cinematic background",
        "negative space for later overlays": "natural dark cinematic background",
        "empty message thread": "phone face down or dark lock screen with no readable interface",
        "phone face down": "closed journal",
        "phone screen showing": "closed journal in soft window light, showing",
        "glowing phone screen": "soft candle glow near a closed journal",
        "a glowing phone screen": "a soft candle glow near a closed journal",
        "phone": "closed journal",
        "dark lock screen": "dark window reflection",
        "waiting-after-a-message mood": "quiet waiting mood",
        "waiting after a message": "quiet waiting mood",
        "vulnerable message": "vulnerable moment",
        "message mood": "quiet mood",
        "DM": "quiet distance",
        "dm": "quiet distance",
        "reply": "distance",
        "read receipt": "silence",
        "read receipts": "silence",
        "few sparse, hesitant words": "blank or blurred pages turned away from camera",
        "sparse words": "blank or blurred pages turned away from camera",
        "written words": "blank or blurred marks with no readable writing",
        "handwriting lines": "soft blurred page texture with no readable writing",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"['\"](?:maybe|yes|no|confusion|possibility|save|wait|waiting|honest)['\"]", "the emotional choice", cleaned, flags=re.IGNORECASE)
    guard = (
        "Real-world photographic scene only, continuous natural background surfaces, "
        "physical objects only, unedited camera frame, no graphic overlay, no captions, "
        "no signage, no readable screens."
    )
    if "real-world photographic scene only" not in cleaned.lower():
        cleaned = cleaned.rstrip(" ,") + ", " + guard
    return cleaned


def _ensure_brand_style(prompt: str) -> str:
    """Append brand style suffix if not already present."""
    prompt = _sanitize_prompt_for_text_artifacts(prompt)
    if "moody editorial cinematic" not in prompt.lower():
        return prompt.rstrip(" ,") + ", " + BRAND_STYLE_SUFFIX
    return prompt


@retry(max_attempts=2, wait_seconds=6, exceptions=(Exception,))
def _generate_via_pollinations(prompt: str, config: dict) -> bytes:
    # Prompt is passed as-is — apply _ensure_brand_style before calling if needed
    encoded = urllib.parse.quote(prompt)
    seed = random.randint(1, 99999)
    api_key = os.environ.get("POLLINATIONS_API_KEY", "")
    url = (
        f"https://gen.pollinations.ai/image/{encoded}"
        f"?model={config['image_model']}"
        f"&width={config['image_width']}"
        f"&height={config['image_height']}"
        f"&seed={seed}"
        f"&enhance=false"
        f"&key={api_key}"
    )
    response = requests.get(url, timeout=45)
    if response.status_code == 200 and len(response.content) > 10000:
        return response.content
    raise Exception(f"Pollinations failed: status={response.status_code} size={len(response.content)}")


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _fetch_pexels_image(
    query: str,
    idx: int,
    used_image_hashes: set[str] | None = None,
) -> bytes:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set")
    headers = {"Authorization": api_key}
    query = _sanitize_stock_query(query)
    params = {"query": query, "orientation": "portrait", "per_page": 12}
    resp = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=20)
    photos = resp.json().get("photos", [])
    if not photos:
        raise Exception(f"Pexels image: no results for '{query}'")
    used_image_hashes = used_image_hashes if used_image_hashes is not None else set()
    start = idx % len(photos)
    ordered = photos[start:] + photos[:start]
    for photo in ordered:
        img_url = photo["src"].get("large2x") or photo["src"].get("large") or photo["src"]["original"]
        content = requests.get(img_url, timeout=30).content
        image_hash = hashlib.sha256(content).hexdigest()
        if image_hash in used_image_hashes:
            continue
        used_image_hashes.add(image_hash)
        return content
    raise Exception(f"Pexels image: all usable results already used for '{query}'")


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _fetch_pexels_clip(
    query: str,
    idx: int,
    output_path: str,
    used_video_ids: set[str] | None = None,
    used_video_hashes: set[str] | None = None,
) -> dict:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set")
    headers = {"Authorization": api_key}
    query = _sanitize_stock_query(query)
    params = {"query": query, "orientation": "portrait", "size": "medium", "per_page": 12}
    resp = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=20)
    videos = resp.json().get("videos", [])
    if not videos:
        raise Exception(f"Pexels video: no results for '{query}'")
    used_video_ids = used_video_ids if used_video_ids is not None else set()
    used_video_hashes = used_video_hashes if used_video_hashes is not None else set()
    start = idx % len(videos)
    ordered = videos[start:] + videos[:start]
    for video in ordered:
        pexels_id = str(video.get("id", ""))
        if pexels_id and pexels_id in used_video_ids:
            continue
        files = sorted(
            [f for f in video["video_files"] if f.get("width")],
            key=lambda x: abs(x["width"] - 1080)
        )
        if not files:
            continue
        r = requests.get(files[0]["link"], timeout=90)
        clip_hash = hashlib.sha256(r.content).hexdigest()
        if clip_hash in used_video_hashes:
            continue
        with open(output_path, "wb") as f:
            f.write(r.content)
        if pexels_id:
            used_video_ids.add(pexels_id)
        used_video_hashes.add(clip_hash)
        return {
            "path": output_path,
            "pexels_id": pexels_id,
            "pexels_hash": clip_hash,
            "query": query,
        }
    raise Exception(f"Pexels video: all usable results already used for '{query}'")


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _fetch_coverr_clip(
    query: str,
    idx: int,
    output_path: str,
    used_video_ids: set[str] | None = None,
    used_video_hashes: set[str] | None = None,
    config: dict | None = None,
) -> dict:
    api_key = os.environ.get("COVERR_API_KEY")
    if not api_key:
        raise RuntimeError("COVERR_API_KEY not set")

    headers = {"Authorization": f"Bearer {api_key}"}
    used_video_ids = used_video_ids if used_video_ids is not None else set()
    used_video_hashes = used_video_hashes if used_video_hashes is not None else set()
    attempted = []

    for coverr_query in _video_query_alternates(query):
        attempted.append(coverr_query)
        params = {
            "query": coverr_query,
            "page_size": int((config or {}).get("coverr_page_size", 50)),
            "sort": "popular",
            "urls": "true",
        }
        resp = requests.get("https://api.coverr.co/videos", headers=headers, params=params, timeout=20)
        if resp.status_code != 200:
            raise Exception(f"Coverr video: status={resp.status_code} for '{coverr_query}'")
        videos = resp.json().get("hits", [])
        vertical = [
            video for video in videos
            if video.get("is_vertical")
            or str(video.get("aspect_ratio", "")).strip() == "9:16"
            or int(video.get("max_height") or 0) > int(video.get("max_width") or 0)
        ]
        candidates = vertical
        orientation_source = "vertical"
        if not candidates and (config or {}).get("coverr_allow_horizontal_crop", True):
            candidates = videos
            orientation_source = "cropped_horizontal"
        if not candidates:
            continue

        start = idx % len(candidates)
        ordered = candidates[start:] + candidates[:start]

        for video in ordered:
            coverr_id = str(video.get("id", ""))
            if coverr_id and coverr_id in used_video_ids:
                continue
            urls = video.get("urls") or {}
            clip_url = urls.get("mp4") or urls.get("mp4_download") or urls.get("mp4_preview")
            if not clip_url:
                continue
            r = requests.get(clip_url, timeout=90)
            if r.status_code != 200:
                continue
            clip_hash = hashlib.sha256(r.content).hexdigest()
            if clip_hash in used_video_hashes:
                continue
            with open(output_path, "wb") as f:
                f.write(r.content)
            if coverr_id:
                used_video_ids.add(coverr_id)
            used_video_hashes.add(clip_hash)
            return {
                "path": output_path,
                "coverr_id": coverr_id,
                "coverr_hash": clip_hash,
                "query": coverr_query,
                "original_query": _sanitize_stock_query(query),
                "description": video.get("description") or video.get("title") or "",
                "tags": video.get("tags", []),
                "duration": video.get("duration"),
                "orientation_source": orientation_source,
            }

    raise Exception(f"Coverr video: no usable results for '{query}' after {attempted}")


def _pick_video_provider(config: dict) -> str:
    weights = config.get("stock_video_provider_weights", {"pexels": 65, "coverr": 35})
    pexels_weight = max(0, int(weights.get("pexels", 65)))
    coverr_weight = max(0, int(weights.get("coverr", 35)))
    if pexels_weight + coverr_weight <= 0:
        return "pexels"
    return random.choices(
        ["pexels", "coverr"],
        weights=[pexels_weight, coverr_weight],
        k=1,
    )[0]


def _save_image(image_bytes: bytes, path: str) -> str:
    if Image is not None:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.save(path)
    else:
        with open(path, "wb") as f:
            f.write(image_bytes)
    return path


def _resize_cover(img: "Image.Image", width: int, height: int) -> "Image.Image":
    scale = max(width / img.width, height / img.height)
    resized = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def _crop_light_matte(img: "Image.Image") -> "Image.Image":
    """Remove white/cream matte borders sometimes returned by image models."""
    rgb = img.convert("RGB")
    src = rgb.load()
    width, height = rgb.size
    col_counts = [0] * width
    row_counts = [0] * height
    for y in range(height):
        for x in range(width):
            r, g, b = src[x, y]
            if not (r >= 238 and g >= 232 and b >= 220):
                col_counts[x] += 1
                row_counts[y] += 1
    min_col_pixels = max(3, int(height * 0.015))
    min_row_pixels = max(3, int(width * 0.015))
    xs = [i for i, count in enumerate(col_counts) if count >= min_col_pixels]
    ys = [i for i, count in enumerate(row_counts) if count >= min_row_pixels]
    if not xs or not ys:
        return img
    left, right = min(xs), max(xs) + 1
    top, bottom = min(ys), max(ys) + 1
    crop_area = (right - left) * (bottom - top)
    image_area = width * height
    if crop_area < image_area * 0.35 or crop_area > image_area * 0.98:
        return img
    return img.crop((left, top, right, bottom))


def _save_generated_image(image_bytes: bytes, path: str, config: dict) -> str:
    if Image is None:
        return _save_image(image_bytes, path)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = _crop_light_matte(img)
    img = _resize_cover(img, int(config["image_width"]), int(config["image_height"]))
    img.save(path)
    return path


def _validate_image(path: str):
    if Image is None:
        return
    img = Image.open(path)
    w, h = img.size
    if w < 300 or h < 400:
        raise Exception(f"Image too small: {w}x{h}")
    if img.mode not in ("RGB", "RGBA"):
        img.convert("RGB").save(path)


def _validate_video(path: str):
    if os.path.getsize(path) < 50_000:
        raise Exception(f"Video file too small: {os.path.getsize(path)} bytes")


def _make_safe_brand_fallback(path: str, label: str):
    if Image is None:
        raise RuntimeError("Pillow not installed")
    _make_placeholder(path, label[:28].upper() or "BRAND IMAGE", (18, 18, 18))


# ── Single-asset generator (image or video) ───────────────────────────────────

def _generate_asset(
    label: str,
    visual_type: str,
    image_prompt: str | None,
    pexels_query: str | None,
    output_path: str,
    idx: int,
    config: dict,
    image_style: str = "brand",
    used_pexels_video_ids: set[str] | None = None,
    used_coverr_video_ids: set[str] | None = None,
    used_pexels_video_hashes: set[str] | None = None,
    used_pexels_image_hashes: set[str] | None = None,
) -> dict:
    """
    Generate one asset (image or video).
    Returns dict with keys: type, source, path (relative).
    Falls back gracefully: selected stock video provider → generated image → Pexels stock image.
    """
    rel_path = os.path.relpath(output_path, start=os.path.dirname(os.path.dirname(output_path)))

    if visual_type == "video":
        query = pexels_query or (image_prompt or "candlelit bedroom")[:40]
        provider = _pick_video_provider(config)
        try:
            if provider == "coverr":
                if not config.get("coverr_enabled", True):
                    raise RuntimeError("Coverr disabled")
                clip_meta = _fetch_coverr_clip(
                    query,
                    idx,
                    output_path,
                    used_coverr_video_ids,
                    used_pexels_video_hashes,
                    config,
                )
                _validate_video(output_path)
                print(f"[image_gen] {label}: video from Coverr ({query})")
                return {
                    "type": "video",
                    "source": "coverr",
                    "path": rel_path,
                    "selected_provider": provider,
                    "coverr_id": clip_meta.get("coverr_id"),
                    "coverr_hash": clip_meta.get("coverr_hash"),
                    "coverr_query": clip_meta.get("query"),
                    "coverr_description": clip_meta.get("description"),
                    "coverr_tags": clip_meta.get("tags", []),
                    "orientation_source": clip_meta.get("orientation_source"),
                }

            clip_meta = _fetch_pexels_clip(
                query,
                idx,
                output_path,
                used_pexels_video_ids,
                used_pexels_video_hashes,
            )
            _validate_video(output_path)
            print(f"[image_gen] {label}: video from Pexels ({query})")
            return {
                "type": "video",
                "source": "pexels",
                "path": rel_path,
                "selected_provider": provider,
                "pexels_id": clip_meta.get("pexels_id"),
                "pexels_hash": clip_meta.get("pexels_hash"),
                "pexels_query": clip_meta.get("query"),
            }
        except Exception as e:
            print(f"[image_gen] {label}: {provider} video failed ({e}) — falling back to generated image")
            image_prompt = image_prompt or (
                f"Moody editorial faceless scene, closed journal near a rainy apartment window, "
                f"scene mood: {query}. {BRAND_STYLE_SUFFIX}"
            )
            output_path = output_path.replace(".mp4", ".png")
            rel_path = rel_path.replace(".mp4", ".png")
            visual_type = "image"
            image_style = "brand"

    # Image path: generate first. Stock images are the last fallback.
    try:
        # Apply brand style suffix only for brand images; context images use their own style
        final_prompt = _ensure_brand_style(image_prompt) if image_style == "brand" else image_prompt
        img_bytes = _generate_via_pollinations(final_prompt, config)
        _save_generated_image(img_bytes, output_path, config)
        _validate_image(output_path)
        print(f"[image_gen] {label}: image from Pollinations [{image_style}]")
        return {"type": "image", "source": "pollinations", "path": rel_path}
    except Exception as e:
        print(f"[image_gen] {label}: Pollinations failed ({e}) — falling back to Pexels stock image")
        query = pexels_query or _extract_pexels_query(image_prompt or "", config)
        img_bytes = _fetch_pexels_image(query, idx, used_pexels_image_hashes)
        _save_image(img_bytes, output_path)
        _validate_image(output_path)
        print(f"[image_gen] {label}: image from Pexels fallback ({query})")
        return {"type": "image", "source": "pexels_fallback", "path": rel_path}


# ── Public entry points ───────────────────────────────────────────────────────

def run_image_gen(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[image_gen] Generating assets for {video_id}")

    manifest = load_json(os.path.join(run_dir, "03b_scene_manifest.json"))
    images_dir = os.path.join(run_dir, "03_images")
    os.makedirs(images_dir, exist_ok=True)

    results = {}
    fallback_count = 0
    video_count = 0
    gap = config.get("image_request_gap_sec", 2)
    used_pexels_video_ids: set[str] = set()
    used_coverr_video_ids: set[str] = set()
    used_pexels_video_hashes: set[str] = set()
    used_pexels_image_hashes: set[str] = set()

    # ── Thumbnail image ───────────────────────────────────────────────────────
    thumb_prompt = _ensure_brand_style(manifest["thumbnail"]["image_prompt"])  # always brand
    thumb_path = os.path.join(images_dir, "thumbnail.png")
    try:
        img_bytes = _generate_via_pollinations(thumb_prompt, config)
        _save_generated_image(img_bytes, thumb_path, config)
        _validate_image(thumb_path)
        results["thumbnail"] = {"type": "image", "source": "pollinations", "path": "03_images/thumbnail.png"}
        print(f"[image_gen] thumbnail: generated")
    except Exception as e:
        print(f"[image_gen] thumbnail: Pollinations failed ({e}) — falling back to Pexels stock image")
        img_bytes = _fetch_pexels_image("candlelit room", 0, used_pexels_image_hashes)
        _save_image(img_bytes, thumb_path)
        _validate_image(thumb_path)
        results["thumbnail"] = {"type": "image", "source": "pexels_fallback", "path": "03_images/thumbnail.png"}
        fallback_count += 1
    time.sleep(gap)

    # Disclaimer card is disabled for Soft Reset With Me.

    # ── Scene assets ──────────────────────────────────────────────────────────
    scenes = manifest["scenes"]
    for i, scene in enumerate(scenes):
        sid = scene["id"]
        vtype = scene["visual_type"]
        ext = ".mp4" if vtype == "video" else ".png"
        out_path = os.path.join(images_dir, f"scene_{sid}{ext}")

        asset = _generate_asset(
            label=f"scene_{sid}",
            visual_type=vtype,
            image_prompt=scene.get("image_prompt"),
            pexels_query=scene.get("pexels_query"),
            output_path=out_path,
            idx=i,
            config=config,
            image_style=scene.get("image_style", "brand"),
            used_pexels_video_ids=used_pexels_video_ids,
            used_coverr_video_ids=used_coverr_video_ids,
            used_pexels_video_hashes=used_pexels_video_hashes,
            used_pexels_image_hashes=used_pexels_image_hashes,
        )

        # Update path in case fallback changed extension
        asset["image_style"] = scene.get("image_style") or ("brand" if vtype == "image" else None)
        results[f"scene_{sid}"] = asset
        if asset["source"] in ("pexels_fallback", "safe_brand_fallback") or (vtype == "video" and asset["type"] == "image"):
            fallback_count += 1
        if asset["type"] == "video":
            video_count += 1

        if i < len(scenes) - 1:
            time.sleep(gap)

    meta = {
        "video_id": video_id,
        "assets": results,
        "total_scenes": len(scenes),
        "video_count": video_count,
        "fallback_count": fallback_count,
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "03_asset_meta.json"))
    total = len(scenes) + 1  # scenes + thumbnail
    print(f"[image_gen] Done. {total - fallback_count}/{total} primary, {fallback_count} fallbacks")
    return meta


# ── Placeholder generator for mock mode ──────────────────────────────────────

def _make_placeholder(path: str, label: str, color: tuple = (10, 10, 10)):
    if Image is None:
        raise RuntimeError("Pillow not installed")
    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (1080, 1920), color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("assets/fonts/Inter-Bold.ttf", 80)
    except Exception:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((1080 - tw) // 2, (1920 - th) // 2), label, fill=(255, 255, 255), font=font)
    img.save(path)


def run_image_gen_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[image_gen][MOCK] Generating placeholder assets for {video_id}")

    manifest = load_json(os.path.join(run_dir, "03b_scene_manifest.json"))
    images_dir = os.path.join(run_dir, "03_images")
    os.makedirs(images_dir, exist_ok=True)

    results = {}

    # Thumbnail placeholder
    thumb_path = os.path.join(images_dir, "thumbnail.png")
    _make_placeholder(thumb_path, "THUMBNAIL", (20, 60, 30))
    results["thumbnail"] = {"type": "image", "source": "mock", "path": "03_images/thumbnail.png"}

    # Disclaimer card is disabled for Soft Reset With Me.

    # Scene placeholders
    for scene in manifest["scenes"]:
        sid = scene["id"]
        label = scene.get("label", f"SCENE {sid}")
        sub = scene.get("covers_dialogue", "")[:30]
        path = os.path.join(images_dir, f"scene_{sid}.png")
        _make_placeholder(path, label, (10, 10, 10))
        results[f"scene_{sid}"] = {"type": "image", "source": "mock", "path": f"03_images/scene_{sid}.png"}
        print(f"[image_gen][MOCK] scene_{sid}: placeholder ({label} — {sub}...)")

    meta = {
        "video_id": video_id,
        "assets": results,
        "total_scenes": len(manifest["scenes"]),
        "video_count": 0,
        "fallback_count": 0,
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "03_asset_meta.json"))
    print(f"[image_gen][MOCK] Done.")
    return meta
