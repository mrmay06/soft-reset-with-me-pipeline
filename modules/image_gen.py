from __future__ import annotations
import os
import time
import random
import urllib.parse

import requests

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry

try:
    from PIL import Image
    import io
except ImportError:
    Image = None
    io = None

try:
    import google.generativeai as genai
except ImportError:
    genai = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_pexels_query(prompt: str, config: dict) -> str:
    """Distil a Pollinations prompt into a short Pexels search query via Gemini."""
    if genai is None:
        return " ".join(prompt.split()[:4])
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return " ".join(prompt.split()[:4])
    genai.configure(api_key=api_key)
    client = genai.GenerativeModel("gemini-2.5-flash")
    response = client.generate_content(
        f"Extract a 3-5 word Pexels stock search query from this image description. "
        f"Return only the search terms, nothing else.\n\nDescription: {prompt}"
    )
    return response.text.strip().lower()


BRAND_STYLE_SUFFIX = (
    "flat cartoon style, thick black outlines, solid flat colors, "
    "bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"
)


def _ensure_brand_style(prompt: str) -> str:
    """Append brand style suffix if not already present."""
    if "chibi art style" not in prompt.lower():
        return prompt.rstrip(" ,") + ", " + BRAND_STYLE_SUFFIX
    return prompt


@retry(max_attempts=3, wait_seconds=8, exceptions=(Exception,))
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
    response = requests.get(url, timeout=90)
    if response.status_code == 200 and len(response.content) > 10000:
        return response.content
    raise Exception(f"Pollinations failed: status={response.status_code} size={len(response.content)}")


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _fetch_pexels_image(query: str, idx: int) -> bytes:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set")
    headers = {"Authorization": api_key}
    params = {"query": query, "orientation": "portrait", "per_page": 5}
    resp = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=20)
    photos = resp.json().get("photos", [])
    if not photos:
        raise Exception(f"Pexels image: no results for '{query}'")
    photo = photos[idx % len(photos)]
    img_url = photo["src"].get("large2x") or photo["src"].get("large") or photo["src"]["original"]
    return requests.get(img_url, timeout=30).content


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _fetch_pexels_clip(query: str, idx: int, output_path: str) -> str:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set")
    headers = {"Authorization": api_key}
    params = {"query": query, "orientation": "portrait", "size": "medium", "per_page": 5}
    resp = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=20)
    videos = resp.json().get("videos", [])
    if not videos:
        raise Exception(f"Pexels video: no results for '{query}'")
    video = videos[idx % len(videos)]
    files = sorted(
        [f for f in video["video_files"] if f.get("width")],
        key=lambda x: abs(x["width"] - 1080)
    )
    r = requests.get(files[0]["link"], timeout=90)
    with open(output_path, "wb") as f:
        f.write(r.content)
    return output_path


def _save_image(image_bytes: bytes, path: str) -> str:
    if Image is not None:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img.save(path)
    else:
        with open(path, "wb") as f:
            f.write(image_bytes)
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
) -> dict:
    """
    Generate one asset (image or video).
    Returns dict with keys: type, source, path (relative).
    Falls back gracefully: Pollinations → Pexels image, or Pexels video → static image.
    """
    rel_path = os.path.relpath(output_path, start=os.path.dirname(os.path.dirname(output_path)))

    if visual_type == "video":
        query = pexels_query or (image_prompt or "finance money")[:40]
        try:
            _fetch_pexels_clip(query, idx, output_path)
            _validate_video(output_path)
            print(f"[image_gen] {label}: video from Pexels ({query})")
            return {"type": "video", "source": "pexels", "path": rel_path}
        except Exception as e:
            print(f"[image_gen] {label}: Pexels video failed ({e}) — falling back to image")
            # Fall through to image generation
            image_prompt = image_prompt or (
                f"Reaction shot: Regular Raccoon — gray chibi raccoon, gold chain, white tee — "
                f"watching scene: {query}. flat cartoon style, thick black outlines, solid flat colors, "
                f"bright yellow background, chibi art style, bold simple shapes, 9:16 vertical"
            )
            output_path = output_path.replace(".mp4", ".png")
            rel_path = rel_path.replace(".mp4", ".png")
            visual_type = "image"

    # Image path
    try:
        # Apply brand style suffix only for brand images; context images use their own style
        final_prompt = _ensure_brand_style(image_prompt) if image_style == "brand" else image_prompt
        img_bytes = _generate_via_pollinations(final_prompt, config)
        _save_image(img_bytes, output_path)
        _validate_image(output_path)
        print(f"[image_gen] {label}: image from Pollinations [{image_style}]")
        return {"type": "image", "source": "pollinations", "path": rel_path}
    except Exception as e:
        print(f"[image_gen] {label}: Pollinations failed ({e}) — falling back to Pexels image")
        query = pexels_query or _extract_pexels_query(image_prompt or "", config)
        img_bytes = _fetch_pexels_image(query, idx)
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

    # ── Thumbnail image ───────────────────────────────────────────────────────
    thumb_prompt = _ensure_brand_style(manifest["thumbnail"]["image_prompt"])  # always brand
    thumb_path = os.path.join(images_dir, "thumbnail.png")
    try:
        img_bytes = _generate_via_pollinations(thumb_prompt, config)
        _save_image(img_bytes, thumb_path)
        _validate_image(thumb_path)
        results["thumbnail"] = {"type": "image", "source": "pollinations", "path": "03_images/thumbnail.png"}
        print(f"[image_gen] thumbnail: generated")
    except Exception as e:
        print(f"[image_gen] thumbnail: Pollinations failed ({e}) — Pexels fallback")
        query = _extract_pexels_query(thumb_prompt, config)
        img_bytes = _fetch_pexels_image(query, 0)
        _save_image(img_bytes, thumb_path)
        results["thumbnail"] = {"type": "image", "source": "pexels_fallback", "path": "03_images/thumbnail.png"}
        fallback_count += 1
    time.sleep(gap)

    # ── Disclaimer — always use the static branded asset ─────────────────────
    results["disclaimer"] = {"type": "image", "source": "static", "path": "assets/disclaimer.png"}
    print(f"[image_gen] disclaimer: using static branded asset")

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
        )

        # Update path in case fallback changed extension
        asset["image_style"] = scene.get("image_style") or ("brand" if vtype == "image" else None)
        results[f"scene_{sid}"] = asset
        if asset["source"] == "pexels_fallback" or (vtype == "video" and asset["type"] == "image"):
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
    total = len(scenes) + 2  # scenes + thumbnail + disclaimer
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
        font = ImageFont.truetype("assets/fonts/Anton-Regular.ttf", 80)
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

    # Disclaimer — always use static branded asset
    results["disclaimer"] = {"type": "image", "source": "static", "path": "assets/disclaimer.png"}

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
