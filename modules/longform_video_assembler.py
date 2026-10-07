from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import random
import re
import subprocess
from datetime import datetime, timezone

import requests

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




def _clip_segment(clip_path: str, duration: float, output_path: str, config: dict):
    fps = int(config.get("longform_fps", 30))
    width = int(config.get("longform_width", 1920))
    height = int(config.get("longform_height", 1080))
    _run_ffmpeg([
        "ffmpeg", "-stream_loop", "-1", "-i", clip_path,
        "-t", str(duration),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,eq=saturation=0.86:contrast=1.04:brightness=-0.025",
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


def _script_queries_for_chapter(script: dict, chapter: dict, idx: int) -> list[str]:
    visual_brief = script.get("visual_brief", [])
    chapter_id = chapter.get("chapter_id", chapter.get("id", idx + 1))
    for item in visual_brief:
        if int(item.get("chapter_id", -1)) == int(chapter_id):
            queries = item.get("stock_queries") or []
            if queries:
                return [_sanitize_query(q) for q in queries[:4] if str(q).strip()]
    return []


def _queries_for_chapter(script: dict, chapter: dict, research: dict, idx: int) -> list[str]:
    return _script_queries_for_chapter(script, chapter, idx) or _fallback_queries(chapter, research, idx)


def _queries_for_beat(script: dict, beat: dict, research: dict, idx: int) -> list[str]:
    text = str(beat.get("voiceover", "")).lower()
    # Preserve deliberate visual direction before broad keyword associations.
    # Otherwise generic matches can fill the query limit and discard the brief.
    queries = _script_queries_for_chapter(script, beat, idx)
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
    if not _script_queries_for_chapter(script, beat, idx):
        queries.extend(_fallback_queries(beat, research, idx))
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
        raise RuntimeError("Clip-only longform requires PEXELS_API_KEY; static fallback cards are disabled")
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


def _planned_final_duration(voice_duration: float, config: dict) -> float:
    """Return the complete visual duration, including the silent narration hold."""
    end_hold_sec = max(0.0, float(config.get("longform_end_hold_sec", 2.0)))
    return float(voice_duration) + end_hold_sec


def _plan_beat_durations(beats: list[dict], voice_duration: float, fps: int) -> list[float]:
    """Fit all beats to one narration timeline, rounded at cumulative boundaries.

    Independent minimum durations and rounding accumulate drift. Reserve just
    one frame per beat and keep every boundary inside the measured voice track.
    """
    if not beats or fps <= 0 or not math.isfinite(voice_duration) or voice_duration <= 0:
        raise ValueError("Visual timing requires beats, positive FPS, and a finite voice duration")
    total_frames = math.ceil(voice_duration * fps)
    if total_frames < len(beats):
        raise ValueError("More visual beats than available narration frames")
    weights = [max(1, word_count(beat.get("voiceover", ""))) for beat in beats]
    total_words = sum(weights)
    cumulative_words = 0
    previous = 0
    durations = []
    for index, weight in enumerate(weights):
        cumulative_words += weight
        remaining = len(beats) - index - 1
        boundary = min(total_frames - remaining,
                       max(previous + 1, round(total_frames * cumulative_words / total_words)))
        durations.append((boundary - previous) / fps)
        previous = boundary
    return durations


def _validate_video(path: str, config: dict, expected_duration: float | None = None) -> dict:
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
    min_duration = float(config.get("longform_validation_min_sec", max(60, float(config.get("longform_target_min_sec", 270)) * 0.85)))
    assert duration >= min_duration, f"Long-form render too short: {duration}"
    if expected_duration is not None:
        tolerance = 1 / int(config.get("longform_fps", 30)) + 0.05
        if abs(duration - expected_duration) > tolerance:
            raise RuntimeError(f"Long-form timing mismatch: rendered {duration}s; expected {expected_duration}s")
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
    end_hold_sec = max(0.0, float(config.get("longform_end_hold_sec", 2.0)))
    final_duration = _planned_final_duration(total_duration, config)
    moving_tail = bool(config.get("longform_moving_tail", False))

    # Joined stock encodes may switch between unspecified and square-pixel SAR.
    # Their dimensions/pixel format are already fixed. Do not let metadata-only
    # changes reset the looping blend/subtitle timeline midway through the film.
    cmd = ["ffmpeg", "-reinit_filter", "0", "-i", concat_path, "-i", audio_source]
    if overlay_enabled:
        cmd += ["-stream_loop", "-1", "-i", overlay_path]
        filter_complex = (
            "[0:v]setsar=1,format=gbrp[base];"
            f"[2:v]scale={width}:{height},format=gbrp[film];"
            f"[base][film]blend=all_mode='{blend_mode}':all_opacity={opacity}[vfilm]"
        )
        video_label = "vfilm"
        print(f"[longform_video] Film overlay: {overlay_path} ({blend_mode}, opacity={opacity})")
    else:
        filter_complex = "[0:v]setsar=1[vfilm]"
        video_label = "vfilm"

    # Bound frame-rounding excess and a looping overlay to the planned timeline.
    # Moving-tail mode already extends the final stock segment before concat.
    visual_duration = final_duration if moving_tail else total_duration
    filter_complex += f";[{video_label}]trim=duration={visual_duration},setpts=PTS-STARTPTS[vbase]"
    video_label = "vbase"

    if captions_enabled:
        caption, caption_method = _caption_filter(captions_path)
        if caption_method == "ass":
            filter_complex += f";[{video_label}]{caption}[vcontent]"
        else:
            filter_complex += f";[{video_label}]null[vcontent]"
    else:
        filter_complex += f";[{video_label}]null[vcontent]"

    if end_hold_sec > 0:
        padding = "null" if moving_tail else f"tpad=stop_mode=clone:stop_duration={end_hold_sec}"
        filter_complex += f";[vcontent]{padding}[vout];[1:a]apad=pad_dur={end_hold_sec}[aout]"
        audio_map = "[aout]"
    else:
        filter_complex += ";[vcontent]null[vout]"
        audio_map = "1:a"

    fade_sec = min(end_hold_sec, max(0.0, float(config.get("longform_end_fade_sec", 0))))
    if fade_sec > 0:
        filter_complex += f";[vout]fade=t=out:st={final_duration - fade_sec:.3f}:d={fade_sec}[vfinal]"
    else:
        filter_complex += ";[vout]null[vfinal]"

    print(f"[longform_video] Captions: {caption_method}")
    _run_ffmpeg([
        *cmd,
        "-filter_complex", filter_complex,
        "-map", "[vfinal]", "-map", audio_map,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-ar", "44100",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
        "-t", str(final_duration),
        output_path, "-y",
    ], "finalize_longform")
    return {
        "captions": captions_enabled,
        "caption_method": caption_method,
        "end_hold_sec": end_hold_sec,
        "moving_tail": moving_tail,
        "ending_fade_sec": fade_sec,
        "film_overlay": {
            "requested": bool(config.get("film_overlay_enabled", False)),
            "applied": overlay_enabled,
            "path": overlay_path,
            "blend_mode": blend_mode,
            "opacity": opacity,
        },
    }


def _longform_clip_history(config: dict) -> tuple[str, list[dict], set[str], set[str]]:
    path = config.get("longform_clip_memory_file", "clip_memory_soft_reset_long.json")
    memory = load_json(path) if os.path.exists(path) else []
    if not isinstance(memory, list) or any(not isinstance(item, dict) for item in memory):
        raise RuntimeError("Long-form clip memory is invalid; restore it instead of silently losing repeat protection")
    days = max(0, int(config.get("longform_clip_reuse_hard_block_days", 30)))
    now = datetime.now(timezone.utc)
    hashes, source_ids = set(), set()
    for item in memory:
        try:
            used = datetime.fromisoformat(str(item.get("used_at", "")).replace("Z", "+00:00"))
            if used.tzinfo is None:
                raise ValueError("timestamp must include timezone")
            recent = max(0, (now - used).total_seconds()) <= days * 86400
        except (TypeError, ValueError):
            # Incomplete dates must not accidentally make a remembered clip
            # eligible. Such entries remain blocked until repaired or removed.
            recent = True
        if recent:
            if item.get("file_hash"):
                hashes.add(str(item["file_hash"]))
            if item.get("provider") and item.get("provider_id"):
                source_ids.add(f"{item['provider']}:{item['provider_id']}")
    return path, memory, hashes, source_ids


def _remember_longform_clip(path: str, memory: list[dict], asset: dict, video_id: str, beat_id: int) -> list[dict]:
    provider = asset["provider"]
    record = {
        "provider": provider,
        "provider_id": str(asset[f"{provider}_id"]),
        "file_hash": asset["hash"],
        "query": asset.get("query", ""),
        "video_id": video_id,
        "beat_id": beat_id,
        "used_at": now_iso(),
    }
    memory = (memory + [record])[-1000:]
    save_json(memory, path)
    return memory


def run_longform_video(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_video] Rendering long-form video for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    voice_meta = load_json(os.path.join(run_dir, "04_longform_voice_meta.json"))
    voice_path = os.path.join(run_dir, "04_longform_voice.mp3")

    chapters = script.get("chapters", [])
    beats = _build_visual_beats(script, config)
    total_duration = float(voice_meta["duration_sec"])
    final_duration = _planned_final_duration(total_duration, config)
    beat_durations = _plan_beat_durations(beats, total_duration, int(config.get("longform_fps", 30)))
    if config.get("longform_moving_tail", False):
        beat_durations[-1] += max(0.0, final_duration - total_duration)

    render_dir = os.path.join(run_dir, "longform_render")
    source_dir = os.path.join(render_dir, "source_clips")
    segment_dir = os.path.join(render_dir, "segments")
    for path in (render_dir, source_dir, segment_dir):
        os.makedirs(path, exist_ok=True)

    segments = []
    visual_assets = []
    memory_path, clip_memory, used_stock_hashes, used_source_ids = _longform_clip_history(config)
    stock_enabled = bool(config.get("longform_stock_video_enabled", True))
    for idx, beat in enumerate(beats):
        duration = beat_durations[idx]
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
            raise RuntimeError(
                f"Clip-only longform failed: no unique stock video for beat {idx + 1}. "
                "No generated-image or static-card fallback is allowed."
            )
        clip_memory = _remember_longform_clip(
            memory_path, clip_memory, asset_info, video_id, beat.get("id", idx + 1)
        )
        visual_assets.append({
            "beat_id": beat.get("id", idx + 1),
            "chapter_id": beat.get("chapter_id"),
            "duration_sec": duration,
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
            final_duration,
            mixed_audio,
            voice_vol=float(config.get("voice_volume", 1.0)),
            music_vol=float(config.get("bg_music_volume", 0.10)),
            fade_out_sec=float(config.get("longform_music_fade_out_sec", 1.5)),
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

    validation = _validate_video(output_path, config, expected_duration=final_duration)
    meta = {
        "video_id": video_id,
        "output": "06_longform_video.mp4",
        "chapters": len(chapters),
        "visual_beats": len(beats),
        "music_track": os.path.basename(music) if music else "none",
        "voice_duration_sec": round(total_duration, 3),
        "planned_final_duration_sec": round(final_duration, 3),
        "planned_visual_duration_sec": round(sum(beat_durations), 3),
        "music_fade_out_sec": (
            float(config.get("longform_music_fade_out_sec", 1.5)) if music else 0.0
        ),
        "visual_assets": visual_assets,
        "stock_video_count": sum(1 for item in visual_assets if item.get("provider") in {"pexels", "coverr"}),
        "pexels_video_count": sum(1 for item in visual_assets if item.get("provider") == "pexels"),
        "coverr_video_count": sum(1 for item in visual_assets if item.get("provider") == "coverr"),
        "fallback_card_count": 0,
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
