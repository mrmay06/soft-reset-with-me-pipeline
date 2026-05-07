from __future__ import annotations

import glob
import hashlib
import json
import os
import random
import re
import subprocess

import requests
from PIL import Image, ImageDraw, ImageFont

from utils.helpers import load_json, save_json, now_iso
from utils.script_contract import word_count
from modules.video_assembler import _mix_audio


def _run_ffmpeg(cmd: list[str], label: str):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"[longform_video] FFmpeg failed ({label}):\n{result.stderr[-1200:]}")


def _has_libass() -> bool:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return result.returncode == 0 and (" ass " in result.stdout or "subtitles" in result.stdout)


def _filter_path(path: str) -> str:
    return os.path.abspath(path).replace("'", "\\'").replace("\\", "/")


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), candidate, font=font)
        if box[2] - box[0] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(draw: ImageDraw.ImageDraw, text: str, font, fill, x: int, y: int, max_width: int, line_gap: int = 18) -> int:
    for line in _wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        box = draw.textbbox((0, 0), line, font=font)
        y += (box[3] - box[1]) + line_gap
    return y


def _chapter_card(chapter: dict, idx: int, total: int, metadata: dict, research: dict, output_path: str, config: dict):
    width = int(config.get("longform_width", 1920))
    height = int(config.get("longform_height", 1080))
    midnight = (28, 28, 43)
    cream = (245, 240, 232)
    terracotta = (196, 120, 90)
    sage = (123, 174, 138)

    image = Image.new("RGB", (width, height), midnight)
    draw = ImageDraw.Draw(image, "RGBA")

    # Editorial, non-template-ish texture from simple translucent blocks.
    draw.rectangle((0, 0, width, height), fill=midnight + (255,))
    draw.rectangle((0, 0, width, 20), fill=terracotta + (255,))
    draw.rectangle((0, height - 22, width, height), fill=sage + (190,))
    draw.rectangle((118, 118, 138, height - 118), fill=terracotta + (210,))
    draw.rectangle((width - 138, 118, width - 118, height - 118), fill=sage + (150,))
    draw.ellipse((width - 560, -240, width + 180, 500), fill=(196, 120, 90, 34))
    draw.ellipse((-260, height - 420, 430, height + 220), fill=(123, 174, 138, 26))

    dm = "assets/fonts/DMSerifDisplay-Regular.ttf"
    inter = "assets/fonts/Inter-Bold.ttf"
    eyebrow_font = _font(inter, 30)
    title_font = _font(dm, 72)
    body_font = _font(dm, 54)
    meta_font = _font(inter, 28)

    draw.text((188, 146), f"SOFT RESET WITH ME  /  {idx + 1:02d}", font=eyebrow_font, fill=terracotta)
    title = metadata.get("title") or research.get("working_title", "")
    _draw_wrapped(draw, title, title_font, cream, 188, 220, 1220, line_gap=18)

    quote = chapter.get("voiceover", "")
    if len(quote) > 210:
        quote = quote[:207].rsplit(" ", 1)[0] + "..."
    _draw_wrapped(draw, quote, body_font, cream, 188, 520, 1300, line_gap=16)

    label = str(chapter.get("label", "chapter")).upper()
    draw.text((188, 900), label, font=meta_font, fill=sage)
    draw.text((width - 420, 900), f"{idx + 1}/{total}", font=meta_font, fill=terracotta)

    image.save(output_path)


def _image_segment(image_path: str, duration: float, output_path: str, config: dict):
    fps = int(config.get("longform_fps", 30))
    width = int(config.get("longform_width", 1920))
    height = int(config.get("longform_height", 1080))
    frames = max(1, int(duration * fps))
    zoompan = (
        "zoompan="
        "z='min(zoom+0.00018,1.08)':"
        "x='iw/2-(iw/zoom/2)':"
        "y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={width}x{height}:fps={fps}"
    )
    _run_ffmpeg([
        "ffmpeg", "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", f"scale={width * 2}:-1,{zoompan},scale={width}:{height}",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], f"image_segment:{output_path}")


def _clip_segment(clip_path: str, duration: float, output_path: str, config: dict):
    fps = int(config.get("longform_fps", 30))
    width = int(config.get("longform_width", 1920))
    height = int(config.get("longform_height", 1080))
    _run_ffmpeg([
        "ffmpeg", "-stream_loop", "-1", "-i", clip_path,
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},eq=saturation=0.86:contrast=1.04:brightness=-0.025",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-an", output_path, "-y"
    ], f"clip_segment:{output_path}")


def _sanitize_query(query: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", str(query or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    symbolic_replacements = {
        "tree": "person alone window",
        "trees": "person alone window",
        "forest": "quiet apartment",
        "storm": "rainy window",
        "stormy sky": "rainy window night",
        "ocean": "city night walking",
        "mountain": "quiet bedroom",
        "roots": "hands journal",
        "flower": "candlelit room",
        "animal": "person alone",
        "journal open pen": "hands writing journal close up",
        "open pen": "hands writing journal close up",
        "notebook pen": "hands writing journal close up",
    }
    for old, new in symbolic_replacements.items():
        if old in cleaned:
            cleaned = new
            break
    return cleaned or "rainy window"


def _fallback_queries(chapter: dict, research: dict, idx: int) -> list[str]:
    label = str(chapter.get("label", "")).lower()
    mood = str(research.get("visual_mood", "")).lower()
    base = []
    if "hook" in label:
        base = ["rainy window night", "person alone window", "city night apartment"]
    elif "pain" in label:
        base = ["empty chair room", "person sitting alone", "quiet bedroom"]
    elif "pattern" in label:
        base = ["hands journal", "walking city night", "train window night"]
    elif "reframe" in label:
        base = ["candlelit room", "closing journal", "morning window"]
    elif "reset" in label or "closing" in label:
        base = ["city walk evening", "open window curtains", "quiet sunrise room"]
    else:
        base = ["rainy apartment window", "city night walking", "candlelit room"]
    if "journal" in mood:
        base.append("hands writing journal")
    if "city" in mood:
        base.append("city night walking")
    return [_sanitize_query(q) for q in base]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", str(text or "").strip())
    return [part.strip() for part in parts if part.strip()]


def _split_dialogue_units(text: str) -> list[str]:
    units = []
    for sentence in _split_sentences(text):
        if word_count(sentence) <= 18:
            units.append(sentence)
            continue
        clauses = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
        current = ""
        for clause in clauses:
            candidate = f"{current} {clause}".strip()
            if current and word_count(candidate) > 18:
                units.append(current)
                current = clause
            else:
                current = candidate
        if current:
            if word_count(current) > 24:
                words = current.split()
                for i in range(0, len(words), 14):
                    units.append(" ".join(words[i:i + 14]))
            else:
                units.append(current)
    return units


def _build_visual_beats(script: dict, config: dict) -> list[dict]:
    target_words = max(12, int(config.get("longform_visual_target_words", 45)))
    max_units = max(1, int(config.get("longform_visual_max_dialogue_units", config.get("longform_visual_max_sentences", 2))))
    beats = []
    beat_id = 1
    for chapter_idx, chapter in enumerate(script.get("chapters", [])):
        dialogue_units = _split_dialogue_units(chapter.get("voiceover", ""))
        current = []
        for unit in dialogue_units:
            candidate_text = " ".join([*current, unit])
            if current and word_count(candidate_text) > target_words:
                beats.append({
                    "id": beat_id,
                    "chapter_id": chapter.get("id", chapter_idx + 1),
                    "label": chapter.get("label", "chapter"),
                    "voiceover": " ".join(current),
                })
                beat_id += 1
                current = []
            current.append(unit)
            current_text = " ".join(current)
            if len(current) >= max_units or word_count(current_text) >= target_words:
                beats.append({
                    "id": beat_id,
                    "chapter_id": chapter.get("id", chapter_idx + 1),
                    "label": chapter.get("label", "chapter"),
                    "voiceover": current_text,
                })
                beat_id += 1
                current = []
        if current:
            beats.append({
                "id": beat_id,
                "chapter_id": chapter.get("id", chapter_idx + 1),
                "label": chapter.get("label", "chapter"),
                "voiceover": " ".join(current),
            })
            beat_id += 1

    max_beats = int(config.get("longform_visual_max_beats", 30))
    while max_beats > 0 and len(beats) > max_beats:
        merged = []
        i = 0
        while i < len(beats):
            if i + 1 < len(beats):
                first, second = beats[i], beats[i + 1]
                first = {
                    **first,
                    "voiceover": f"{first.get('voiceover', '')} {second.get('voiceover', '')}".strip(),
                }
                merged.append(first)
                i += 2
            else:
                merged.append(beats[i])
                i += 1
        beats = [{**beat, "id": idx + 1} for idx, beat in enumerate(merged)]
    return beats


def _queries_for_chapter(script: dict, chapter: dict, research: dict, idx: int) -> list[str]:
    visual_brief = script.get("visual_brief", [])
    for item in visual_brief:
        if int(item.get("chapter_id", -1)) == int(chapter.get("id", idx + 1)):
            queries = item.get("stock_queries") or []
            if queries:
                return [_sanitize_query(q) for q in queries[:4]]
    return _fallback_queries(chapter, research, idx)


def _queries_for_beat(script: dict, beat: dict, research: dict, idx: int) -> list[str]:
    text = str(beat.get("voiceover", "")).lower()
    queries = []
    if any(term in text for term in ["phone", "text", "screen", "dm", "message", "scroll"]):
        queries.extend(["phone screen bed", "person looking at phone", "phone screen night"])
    if any(term in text for term in ["chaos", "anxiety", "inconsistent", "withdrawal", "rush"]):
        queries.extend(["person alone window night", "rainy window night", "city night alone"])
    if any(term in text for term in ["peace", "calm", "steady", "safe", "quiet"]):
        queries.extend(["quiet morning room", "person calm window", "slow city walk"])
    if any(term in text for term in ["journal", "write", "question", "truth"]):
        queries.extend(["hands journaling close up", "hands writing journal", "journal open pen"])
    if any(term in text for term in ["relationship", "love", "person", "people"]):
        queries.extend(["two people sitting couch calm", "person sitting alone room"])
    queries.extend(_queries_for_chapter(script, beat, research, idx))
    deduped = []
    for query in queries:
        sanitized = _sanitize_query(query)
        if sanitized not in deduped:
            deduped.append(sanitized)
    return deduped[:5]


def _top_result_order(items: list[dict], config: dict) -> list[dict]:
    sample_size = max(1, int(config.get("longform_stock_video_top_sample_size", 6)))
    top_items = items[:sample_size]
    rest = items[sample_size:]
    random.shuffle(top_items)
    return top_items + rest


def _candidate_text(video: dict) -> str:
    parts = [
        str(video.get("description") or ""),
        str(video.get("title") or ""),
        str(video.get("url") or ""),
    ]
    tags = video.get("tags") or []
    if isinstance(tags, list):
        parts.extend(str(tag) for tag in tags)
    return " ".join(parts).lower()


def _is_brand_fit_candidate(video: dict, config: dict) -> bool:
    block_terms = config.get("longform_stock_video_block_terms", [])
    text = _candidate_text(video)
    return not any(str(term).lower() in text for term in block_terms)


def _fetch_pexels_clip(
    queries: list[str],
    idx: int,
    output_path: str,
    config: dict,
    used_hashes: set[str],
    used_source_ids: set[str],
) -> dict | None:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        print("[longform_video] PEXELS_API_KEY missing; using fallback card")
        return None
    headers = {"Authorization": api_key}
    per_page = int(config.get("longform_stock_video_per_page", 10))
    for query in queries:
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={"query": query, "orientation": "landscape", "size": "medium", "per_page": per_page},
                timeout=20,
            )
            videos = resp.json().get("videos", [])
            if not videos:
                continue
            for video in _top_result_order(videos, config):
                source_id = f"pexels:{video.get('id', '')}"
                if source_id in used_source_ids:
                    continue
                if not _is_brand_fit_candidate(video, config):
                    continue
                files = sorted(
                    [f for f in video.get("video_files", []) if f.get("width") and f.get("link")],
                    key=lambda f: abs(int(f.get("width", 0)) - 1920),
                )
                for file_info in files:
                    clip = requests.get(file_info["link"], timeout=90).content
                    clip_hash = hashlib.sha256(clip).hexdigest()
                    if clip_hash in used_hashes:
                        continue
                    with open(output_path, "wb") as f:
                        f.write(clip)
                    used_hashes.add(clip_hash)
                    used_source_ids.add(source_id)
                    return {
                        "provider": "pexels",
                        "query": query,
                        "pexels_id": str(video.get("id", "")),
                        "hash": clip_hash,
                    }
        except Exception as exc:
            print(f"[longform_video] Pexels query failed '{query}': {exc}")
    return None


def _fetch_coverr_clip(
    queries: list[str],
    idx: int,
    output_path: str,
    config: dict,
    used_hashes: set[str],
    used_source_ids: set[str],
) -> dict | None:
    if not config.get("coverr_enabled", True):
        return None
    api_key = os.environ.get("COVERR_API_KEY")
    if not api_key:
        print("[longform_video] COVERR_API_KEY missing; trying next provider")
        return None
    headers = {"Authorization": f"Bearer {api_key}"}
    page_size = int(config.get("coverr_page_size", 50))
    for query in queries:
        try:
            resp = requests.get(
                "https://api.coverr.co/videos",
                headers=headers,
                params={"query": query, "page_size": page_size, "sort": "popular", "urls": "true"},
                timeout=20,
            )
            if resp.status_code != 200:
                print(f"[longform_video] Coverr status {resp.status_code} for '{query}'")
                continue
            videos = resp.json().get("hits", [])
            if not videos:
                continue
            for video in _top_result_order(videos, config):
                source_id = f"coverr:{video.get('id', '')}"
                if source_id in used_source_ids:
                    continue
                if not _is_brand_fit_candidate(video, config):
                    continue
                urls = video.get("urls") or {}
                clip_url = urls.get("mp4") or urls.get("mp4_download") or urls.get("mp4_preview")
                if not clip_url:
                    continue
                clip = requests.get(clip_url, timeout=90).content
                clip_hash = hashlib.sha256(clip).hexdigest()
                if clip_hash in used_hashes:
                    continue
                with open(output_path, "wb") as f:
                    f.write(clip)
                used_hashes.add(clip_hash)
                used_source_ids.add(source_id)
                return {
                    "provider": "coverr",
                    "query": query,
                    "coverr_id": str(video.get("id", "")),
                    "hash": clip_hash,
                    "description": video.get("description") or video.get("title") or "",
                    "tags": video.get("tags", []),
                }
        except Exception as exc:
            print(f"[longform_video] Coverr query failed '{query}': {exc}")
    return None


def _provider_order(config: dict) -> list[str]:
    weights = config.get("longform_stock_video_provider_weights", {"pexels": 65, "coverr": 35})
    providers = ["pexels", "coverr"]
    pexels_weight = max(0, int(weights.get("pexels", 65)))
    coverr_weight = max(0, int(weights.get("coverr", 35)))
    if pexels_weight + coverr_weight <= 0:
        return ["pexels", "coverr"]
    first = random.choices(providers, weights=[pexels_weight, coverr_weight], k=1)[0]
    return [first] + [provider for provider in providers if provider != first]


def _fetch_stock_clip(
    queries: list[str],
    idx: int,
    output_path: str,
    config: dict,
    used_hashes: set[str],
    used_source_ids: set[str],
) -> dict | None:
    for provider in _provider_order(config):
        provider_path = output_path.replace(".mp4", f"_{provider}.mp4")
        if provider == "pexels":
            meta = _fetch_pexels_clip(queries, idx, provider_path, config, used_hashes, used_source_ids)
        else:
            meta = _fetch_coverr_clip(queries, idx, provider_path, config, used_hashes, used_source_ids)
        if meta:
            os.replace(provider_path, output_path)
            return meta
    return None


def _concat(segments: list[str], output_path: str):
    list_path = output_path.replace(".mp4", "_list.txt")
    with open(list_path, "w") as f:
        for seg in segments:
            f.write(f"file '{os.path.abspath(seg)}'\n")
    _run_ffmpeg([
        "ffmpeg", "-f", "concat", "-safe", "0", "-i", list_path,
        "-c", "copy", output_path, "-y"
    ], "concat")


def _pick_music_track() -> str | None:
    tracks = glob.glob("assets/music/*.mp3")
    return random.choice(tracks) if tracks else None


def _validate_video(path: str, config: dict) -> dict:
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=width,height,codec_name:format=duration",
        "-of", "json", path
    ], capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    stream = info["streams"][0]
    duration = float(info["format"]["duration"])
    assert stream["codec_name"] == "h264", f"Wrong codec: {stream['codec_name']}"
    assert stream["width"] == int(config.get("longform_width", 1920))
    assert stream["height"] == int(config.get("longform_height", 1080))
    min_duration = float(config.get("longform_validation_min_sec", max(60, float(config.get("longform_target_min_sec", 300)) * 0.85)))
    assert duration >= min_duration, f"Long-form render too short: {duration}"
    return {
        "duration_sec": round(duration, 2),
        "width": stream["width"],
        "height": stream["height"],
        "codec": stream["codec_name"],
    }


def _caption_filter(captions_path: str) -> tuple[str, str]:
    if _has_libass():
        return f"ass='{_filter_path(captions_path)}':fontsdir='{_filter_path('assets/fonts')}'", "ass"
    return "null", "disabled_no_libass"


def _film_overlay_settings(config: dict) -> tuple[str, bool, str, float]:
    overlay_path = config.get("film_overlay_path", "assets/Old Film Overlay.mp4")
    enabled = bool(config.get("film_overlay_enabled", False)) and os.path.exists(overlay_path)
    blend_mode = config.get("film_overlay_blend_mode", "screen")
    opacity = float(config.get("film_overlay_opacity", 0.14))
    return overlay_path, enabled, blend_mode, opacity


def _finalize_longform(
    concat_path: str,
    audio_source: str,
    captions_path: str | None,
    output_path: str,
    config: dict,
    total_duration: float,
) -> dict:
    crf = int(config.get("longform_crf", 23))
    fps = int(config.get("longform_fps", 30))
    width = int(config.get("longform_width", 1920))
    height = int(config.get("longform_height", 1080))
    overlay_path, overlay_enabled, blend_mode, opacity = _film_overlay_settings(config)
    captions_enabled = bool(captions_path and os.path.exists(captions_path))
    caption_method = "none"

    cmd = ["ffmpeg", "-i", concat_path, "-i", audio_source]
    if overlay_enabled:
        cmd += ["-stream_loop", "-1", "-i", overlay_path]
        filter_complex = (
            "[0:v]format=gbrp[base];"
            f"[2:v]scale={width}:{height},format=gbrp[film];"
            f"[base][film]blend=all_mode='{blend_mode}':all_opacity={opacity}[vfilm]"
        )
        video_label = "vfilm"
        print(f"[longform_video] Film overlay: {overlay_path} ({blend_mode}, opacity={opacity})")
    else:
        filter_complex = "[0:v]null[vfilm]"
        video_label = "vfilm"

    if captions_enabled:
        caption, caption_method = _caption_filter(captions_path)
        if caption_method == "ass":
            filter_complex += f";[{video_label}]{caption}[vout]"
        else:
            filter_complex += f";[{video_label}]null[vout]"
    else:
        filter_complex += f";[{video_label}]null[vout]"

    print(f"[longform_video] Captions: {caption_method}")
    _run_ffmpeg([
        *cmd,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-ar", "44100",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
        "-t", str(total_duration),
        output_path, "-y",
    ], "finalize_longform")
    return {
        "captions": captions_enabled,
        "caption_method": caption_method,
        "film_overlay": {
            "requested": bool(config.get("film_overlay_enabled", False)),
            "applied": overlay_enabled,
            "path": overlay_path,
            "blend_mode": blend_mode,
            "opacity": opacity,
        },
    }


def run_longform_video(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_video] Rendering long-form video for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    voice_meta = load_json(os.path.join(run_dir, "04_longform_voice_meta.json"))
    voice_path = os.path.join(run_dir, "04_longform_voice.mp3")

    chapters = script.get("chapters", [])
    beats = _build_visual_beats(script, config)
    total_words = max(1, sum(word_count(beat.get("voiceover", "")) for beat in beats))
    total_duration = float(voice_meta["duration_sec"])

    render_dir = os.path.join(run_dir, "longform_render")
    source_dir = os.path.join(render_dir, "source_clips")
    segment_dir = os.path.join(render_dir, "segments")
    card_dir = os.path.join(render_dir, "cards")
    for path in (render_dir, source_dir, segment_dir, card_dir):
        os.makedirs(path, exist_ok=True)

    segments = []
    visual_assets = []
    used_stock_hashes: set[str] = set()
    used_source_ids: set[str] = set()
    stock_enabled = bool(config.get("longform_stock_video_enabled", True))
    for idx, beat in enumerate(beats):
        beat_words = max(1, word_count(beat.get("voiceover", "")))
        duration = max(3.2, total_duration * beat_words / total_words)
        card = os.path.join(card_dir, f"beat_{idx + 1:02d}.png")
        seg = os.path.join(segment_dir, f"beat_{idx + 1:02d}.mp4")
        asset_info = None
        if stock_enabled:
            clip_path = os.path.join(source_dir, f"beat_{idx + 1:02d}_stock.mp4")
            queries = _queries_for_beat(script, beat, research, idx)
            asset_info = _fetch_stock_clip(queries, idx, clip_path, config, used_stock_hashes, used_source_ids)
            if asset_info:
                _clip_segment(clip_path, duration, seg, config)
                asset_info["path"] = os.path.relpath(clip_path, run_dir)
        if not asset_info:
            _chapter_card(beat, idx, len(beats), metadata, research, card, config)
            _image_segment(card, duration, seg, config)
            asset_info = {
                "provider": "fallback_card",
                "query": "",
                "path": os.path.relpath(card, run_dir),
            }
        visual_assets.append({
            "beat_id": beat.get("id", idx + 1),
            "chapter_id": beat.get("chapter_id"),
            **asset_info,
        })
        segments.append(seg)
        print(f"[longform_video] beat_{idx + 1:02d} segment {duration:.1f}s ({asset_info['provider']})")

    concat_path = os.path.join(run_dir, "05_longform_concat.mp4")
    _concat(segments, concat_path)

    music = _pick_music_track()
    audio_source = voice_path
    if music:
        mixed_audio = os.path.join(run_dir, "05_longform_audio_mix.aac")
        print(f"[longform_video] Mixing audio with {os.path.basename(music)}")
        _mix_audio(
            voice_path,
            music,
            total_duration,
            mixed_audio,
            voice_vol=float(config.get("voice_volume", 1.0)),
            music_vol=float(config.get("bg_music_volume", 0.10)),
            fade_out_sec=4.0,
            target_lufs=float(config.get("final_audio_lufs", -16)),
            true_peak=float(config.get("final_audio_true_peak", -1.5)),
            lra=float(config.get("final_audio_lra", 11)),
        )
        audio_source = mixed_audio

    output_path = os.path.join(run_dir, "06_longform_video.mp4")
    captions_path = os.path.join(run_dir, "04_longform_captions.ass")
    final_features = {"captions": False, "caption_method": "none", "film_overlay": {"applied": False}}
    if not config.get("longform_captions_enabled", True) or not os.path.exists(captions_path):
        captions_path = None
    final_features = _finalize_longform(concat_path, audio_source, captions_path, output_path, config, total_duration)

    validation = _validate_video(output_path, config)
    meta = {
        "video_id": video_id,
        "output": "06_longform_video.mp4",
        "chapters": len(chapters),
        "visual_beats": len(beats),
        "music_track": os.path.basename(music) if music else "none",
        "visual_assets": visual_assets,
        "stock_video_count": sum(1 for item in visual_assets if item.get("provider") in {"pexels", "coverr"}),
        "pexels_video_count": sum(1 for item in visual_assets if item.get("provider") == "pexels"),
        "coverr_video_count": sum(1 for item in visual_assets if item.get("provider") == "coverr"),
        "fallback_card_count": sum(1 for item in visual_assets if item.get("provider") == "fallback_card"),
        **final_features,
        "validation": "passed",
        "generated_at": now_iso(),
        **validation,
    }
    save_json(meta, os.path.join(run_dir, "06_longform_render_meta.json"))
    print(f"[longform_video] Done. Final video: {validation['duration_sec']}s")
    return meta


def run_longform_video_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_video][MOCK] Creating lightweight long-form placeholder for {video_id}")
    output_path = os.path.join(run_dir, "06_longform_video.mp4")
    duration = min(float(config.get("longform_target_max_sec", 120)), 12.0)
    width = int(config.get("longform_width", 1920))
    height = int(config.get("longform_height", 1080))
    fps = int(config.get("longform_fps", 30))
    _run_ffmpeg([
        "ffmpeg",
        "-f", "lavfi",
        "-i", f"color=c=0x1C1C2B:s={width}x{height}:d={duration}:r={fps}",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:d={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        output_path,
        "-y",
    ], "mock_longform_video")
    meta = {
        "video_id": video_id,
        "output": "06_longform_video.mp4",
        "chapters": len(load_json(os.path.join(run_dir, "02_longform_script.json")).get("chapters", [])),
        "visual_beats": 0,
        "music_track": "mock",
        "visual_assets": [],
        "stock_video_count": 0,
        "pexels_video_count": 0,
        "coverr_video_count": 0,
        "fallback_card_count": 0,
        "captions": False,
        "caption_method": "mock",
        "film_overlay": {"applied": False},
        "validation": "passed",
        "duration_sec": duration,
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "06_longform_render_meta.json"))
    print(f"[longform_video][MOCK] Done. Final video: {duration}s")
    return meta
