from __future__ import annotations
import os
import json
import re
import random
import subprocess
import glob

from PIL import Image, ImageDraw, ImageFont

from utils.helpers import load_json, save_json, now_iso


def _has_libass() -> bool:
    """Check whether this FFmpeg build has the ass/subtitles filter (requires libass)."""
    result = subprocess.run(
        ["ffmpeg", "-filters"],
        capture_output=True, text=True
    )
    return " ass " in result.stdout or "subtitles" in result.stdout


def _parse_ass_dialogues(ass_path: str) -> list[dict]:
    """Parse Dialogue lines from an ASS file into {start, end, text} dicts."""
    dialogues = []
    with open(ass_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.startswith("Dialogue:"):
                continue
            parts = line.split(",", 9)
            if len(parts) < 10:
                continue
            start_str = parts[1].strip()
            end_str   = parts[2].strip()
            raw_text  = parts[9].strip()
            # Strip ASS override tags like {\k10}, {\an8}, etc.
            clean_text = re.sub(r"\{[^}]*\}", "", raw_text).strip()
            if not clean_text:
                continue

            def _ass_ts_to_sec(ts: str) -> float:
                h, m, s_cs = ts.split(":")
                s, cs = s_cs.split(".")
                return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100

            dialogues.append({
                "start": _ass_ts_to_sec(start_str),
                "end":   _ass_ts_to_sec(end_str),
                "text":  clean_text,
            })
    return dialogues


def _build_drawtext_filter(ass_path: str, font_path: str = "assets/fonts/Inter-Bold.ttf") -> str:
    """Build a chain of drawtext filters from ASS dialogue lines (libass-free fallback)."""
    dialogues = _parse_ass_dialogues(ass_path)
    if not dialogues:
        return "null"

    abs_font = os.path.abspath(font_path)
    parts = []
    for d in dialogues:
        # Escape special characters for FFmpeg drawtext
        text = d["text"].title().replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")
        part = (
            f"drawtext="
            f"fontfile='{abs_font}':"
            f"text='{text}':"
            f"fontsize=82:"
            f"fontcolor=0xF5F0E8:"
            f"borderw=4:"
            f"bordercolor=0x1C1C2B:"
            f"x=(w-text_w)/2:"
            f"y=(h-text_h)/2:"
            f"enable='between(t,{d['start']:.3f},{d['end']:.3f})'"
        )
        parts.append(part)

    # Chain all drawtext filters separated by commas
    return ",".join(parts)


KB_PATTERNS = [
    # 1 — zoom in center
    "z='min(zoom+0.0015,1.5)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # 2 — zoom out center
    "z='if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0015))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
    # 3 — zoom in + pan right (px = prev x; starts at 0 and drifts right 0.8px/frame)
    "z='min(zoom+0.001,1.3)':x='min(px+0.8,iw-iw/zoom)':y='ih/2-(ih/zoom/2)'",
    # 4 — zoom in + pan left (starts at center and drifts left 0.8px/frame, floored at 0)
    "z='min(zoom+0.001,1.3)':x='max(iw/2-(iw/zoom/2)-px*0.8,0)':y='ih/2-(ih/zoom/2)'",
    # 5 — slow zoom in center
    "z='min(zoom+0.0008,1.2)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'",
]


def _run_ffmpeg(cmd: list, label: str):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"[video] FFmpeg failed ({label}):\n{result.stderr[-1000:]}")


def _image_to_segment(image_path: str, duration: float, pattern_index: int, output_path: str, fps: int = 30):
    frames = max(1, int(duration * fps))
    pattern = KB_PATTERNS[pattern_index % 5]
    zoompan = f"zoompan={pattern}:d={frames}:s=1080x1920:fps={fps}"

    _run_ffmpeg([
        "ffmpeg", "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", f"scale=2160:-1,{zoompan},scale=1080:1920",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], f"image_to_segment:{output_path}")


def _clip_to_segment(clip_path: str, duration: float, output_path: str, fps: int = 30):
    _run_ffmpeg([
        "ffmpeg", "-stream_loop", "-1", "-i", clip_path,
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-an", output_path, "-y"
    ], f"clip_to_segment:{output_path}")


def _static_image_to_segment(image_path: str, duration: float, output_path: str, fps: int = 30):
    _run_ffmpeg([
        "ffmpeg", "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", "scale=1080:1920",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], f"static_to_segment:{output_path}")


def _hex_to_rgb(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not isinstance(value, str):
        return fallback
    clean = value.strip().lstrip("#")
    if len(clean) != 6:
        return fallback
    try:
        return tuple(int(clean[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _load_brand_font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default()


def _fit_font(draw: ImageDraw.ImageDraw, text: str, font_path: str, max_width: int,
              start_size: int, min_size: int = 36):
    size = start_size
    while size > min_size:
        font = _load_brand_font(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 4
    return _load_brand_font(font_path, min_size)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font,
    fill: tuple[int, int, int],
    width: int = 1080,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int] | None = None,
) -> int:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2
    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
    return y + text_h


def _create_cta_card(run_dir: str, config: dict) -> str:
    custom_card_path = config.get("cta_card_image_path")
    if custom_card_path and os.path.exists(custom_card_path):
        output_path = os.path.join(run_dir, "06_cta_card.png")
        Image.open(custom_card_path).convert("RGB").resize((1080, 1920), Image.LANCZOS).save(output_path)
        return output_path

    colors = config.get("brand_colors", {})
    midnight = _hex_to_rgb(colors.get("deep_midnight"), (28, 28, 43))
    terracotta = _hex_to_rgb(colors.get("warm_terracotta"), (196, 120, 90))
    cream = _hex_to_rgb(colors.get("soft_cream"), (245, 240, 232))
    sage = _hex_to_rgb(colors.get("sage_green"), (123, 174, 138))

    dm_serif = "assets/fonts/DMSerifDisplay-Regular.ttf"
    inter = "assets/fonts/Inter-Bold.ttf"

    primary = config.get("cta_card_primary", "Save this for later")
    secondary = config.get("cta_card_secondary", "Subscribe for softer resets")
    handle = config.get("channel_handle", "@SoftResetWithMe")
    logo_text = config.get("cta_card_logo_text", "Soft Reset")
    logo_subtext = config.get("cta_card_logo_subtext", "With Me")

    image = Image.new("RGB", (1080, 1920), midnight)
    draw = ImageDraw.Draw(image, "RGBA")

    # Editorial frame: simple brand color accents, no generated-image text dependency.
    draw.rectangle((88, 248, 102, 1672), fill=terracotta + (255,))
    draw.rectangle((978, 248, 992, 1672), fill=sage + (190,))
    draw.line((170, 418, 910, 418), fill=terracotta + (120,), width=2)
    draw.line((170, 1502, 910, 1502), fill=sage + (120,), width=2)

    logo_font = _fit_font(draw, logo_text, dm_serif, max_width=780, start_size=126, min_size=72)
    logo_y = 520
    _draw_centered_text(draw, logo_text, logo_y, logo_font, cream)

    sub_font = _fit_font(draw, logo_subtext.upper(), inter, max_width=520, start_size=42, min_size=28)
    _draw_centered_text(draw, logo_subtext.upper(), logo_y + 185, sub_font, sage)

    cta_font = _fit_font(draw, primary, dm_serif, max_width=860, start_size=104, min_size=58)
    cta_y = 928
    _draw_centered_text(
        draw,
        primary,
        cta_y,
        cta_font,
        cream,
        stroke_width=2,
        stroke_fill=midnight,
    )

    secondary_font = _fit_font(draw, secondary.upper(), inter, max_width=820, start_size=42, min_size=28)
    _draw_centered_text(draw, secondary.upper(), 1110, secondary_font, terracotta)

    handle_font = _fit_font(draw, handle, inter, max_width=760, start_size=46, min_size=30)
    _draw_centered_text(draw, handle, 1310, handle_font, cream)

    output_path = os.path.join(run_dir, "06_cta_card.png")
    image.save(output_path)
    return output_path


def _concat_with_xfade(segments: list, output_path: str, fps: int = 30, xfade_duration: float = 0.4):
    if len(segments) == 1:
        import shutil
        shutil.copy(segments[0][0], output_path)
        return

    inputs = []
    for path, _ in segments:
        inputs += ["-i", path]

    filter_parts = []
    current = "[0:v]"
    cumulative_offset = 0.0

    for i in range(1, len(segments)):
        prev_duration = segments[i - 1][1]
        cumulative_offset += prev_duration - xfade_duration
        next_label = f"[v{i}]"
        filter_parts.append(
            f"{current}[{i}:v]xfade=transition=fade:duration={xfade_duration}:offset={cumulative_offset:.3f}{next_label}"
        )
        current = next_label

    filter_str = ";".join(filter_parts)

    _run_ffmpeg([
        "ffmpeg", *inputs,
        "-filter_complex", filter_str,
        "-map", current,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], "concat_xfade")


def _mix_audio(voice_path: str, music_path: str, total_duration: float, output_path: str,
               voice_vol: float = 1.0, music_vol: float = 0.13, fade_out_sec: float = 2.0,
               target_lufs: float = -16, true_peak: float = -1.5, lra: float = 11):
    fade_start = max(0, total_duration - fade_out_sec)
    _run_ffmpeg([
        "ffmpeg",
        "-i", voice_path,
        "-stream_loop", "-1", "-i", music_path,
        "-t", str(total_duration),
        "-filter_complex",
        (
            f"[0:a]volume={voice_vol},apad,atrim=0:{total_duration}[voice];"
            f"[1:a]volume={music_vol},atrim=0:{total_duration},"
            f"afade=t=out:st={fade_start:.3f}:d={fade_out_sec}[music];"
            f"[voice][music]amix=inputs=2:duration=first,"
            f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra},"
            f"alimiter=limit=0.84[aout]"
        ),
        "-map", "[aout]",
        "-c:a", "aac", "-ar", "44100",
        output_path, "-y"
    ], "mix_audio")


def _xfaded_duration(segments: list, xfade_duration: float) -> float:
    if not segments:
        return 0.0
    overlap = max(0, len(segments) - 1) * xfade_duration
    return max(0.1, sum(duration for _, duration in segments) - overlap)


def _compensate_scene_durations_for_xfade(
    scenes: list[dict],
    static_segment_count: int,
    xfade_duration: float,
) -> list[float]:
    if not scenes:
        return []
    total_segments = len(scenes) + static_segment_count
    total_overlap = max(0, total_segments - 1) * xfade_duration
    extra_per_scene = total_overlap / len(scenes)
    return [
        max(0.1, scene.get("duration_sec", 3.0) + extra_per_scene)
        for scene in scenes
    ]


def _filter_path(path: str) -> str:
    return os.path.abspath(path).replace("'", "\\'").replace("\\", "/")


def _build_caption_filter(captions_path: str) -> tuple[str, str]:
    if _has_libass():
        safe_captions = _filter_path(captions_path)
        fonts_dir = _filter_path("assets/fonts")
        return f"ass='{safe_captions}':fontsdir='{fonts_dir}'", "ass (libass)"

    return _build_drawtext_filter(captions_path), "drawtext (libass fallback)"


def _film_overlay_settings(config: dict) -> tuple[str, bool, str, float]:
    overlay_path = config.get("film_overlay_path", "assets/Old Film Overlay.mp4")
    enabled = bool(config.get("film_overlay_enabled", False)) and os.path.exists(overlay_path)
    blend_mode = config.get("film_overlay_blend_mode", "screen")
    opacity = float(config.get("film_overlay_opacity", 0.18))
    return overlay_path, enabled, blend_mode, opacity


def _assemble_final(
    video_path: str,
    audio_path: str,
    captions_path: str,
    output_path: str,
    config: dict,
    total_duration: float,
):
    crf = config.get("video_crf", 23)
    fps = config.get("video_fps", 30)
    caption_filter, caption_method = _build_caption_filter(captions_path)
    overlay_path, overlay_enabled, blend_mode, opacity = _film_overlay_settings(config)

    base_cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", audio_path,
    ]

    if overlay_enabled:
        filter_complex = (
            "[0:v]format=gbrp[base];"
            "[2:v]scale=1080:1920,format=gbrp[film];"
            f"[base][film]blend=all_mode='{blend_mode}':all_opacity={opacity}[vfilm];"
            f"[vfilm]{caption_filter}[vout]"
        )
        base_cmd += ["-stream_loop", "-1", "-i", overlay_path]
        print(f"[assembler] Film overlay: {overlay_path} ({blend_mode}, opacity={opacity})")
    else:
        if config.get("film_overlay_enabled", False):
            print(f"[assembler] Film overlay missing, skipping: {overlay_path}")
        filter_complex = f"[0:v]{caption_filter}[vout]"

    print(f"[assembler] Caption method: {caption_method}")
    _run_ffmpeg([
        *base_cmd,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-ar", "44100",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-movflags", "+faststart",
        "-t", str(total_duration),
        output_path, "-y",
    ], "assemble_final")
    return overlay_enabled


def _assemble_without_captions(
    video_path: str,
    audio_path: str,
    output_path: str,
    config: dict,
    total_duration: float,
) -> bool:
    crf = config.get("video_crf", 23)
    fps = config.get("video_fps", 30)
    overlay_path, overlay_enabled, blend_mode, opacity = _film_overlay_settings(config)

    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", audio_path,
    ]

    if overlay_enabled:
        filter_complex = (
            "[0:v]format=gbrp[base];"
            "[2:v]scale=1080:1920,format=gbrp[film];"
            f"[base][film]blend=all_mode='{blend_mode}':all_opacity={opacity}[vout]"
        )
        cmd += ["-stream_loop", "-1", "-i", overlay_path]
        video_map = "[vout]"
        print(f"[assembler] Film overlay without captions: {overlay_path} ({blend_mode}, opacity={opacity})")
    else:
        if config.get("film_overlay_enabled", False):
            print(f"[assembler] Film overlay missing, skipping: {overlay_path}")
        filter_complex = "[0:v]null[vout]"
        video_map = "[vout]"

    _run_ffmpeg([
        *cmd,
        "-filter_complex", filter_complex,
        "-map", video_map, "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-ar", "44100",
        "-pix_fmt", "yuv420p",
        "-r", str(fps),
        "-movflags", "+faststart",
        "-t", str(total_duration),
        output_path, "-y",
    ], "assemble_no_captions")
    return overlay_enabled


def _validate_final_video(path: str):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,duration,codec_name",
        "-of", "json", path
    ], capture_output=True, text=True)

    info = json.loads(result.stdout)["streams"][0]
    assert info["codec_name"] == "h264", f"Wrong codec: {info['codec_name']}"
    assert info["width"] == 1080, f"Wrong width: {info['width']}"
    assert info["height"] == 1920, f"Wrong height: {info['height']}"
    assert float(info["duration"]) <= 60.0, f"Too long: {info['duration']}s"
    assert float(info["duration"]) >= 10.0, f"Too short: {info['duration']}s"
    return float(info["duration"])


def _pick_music_track() -> str | None:
    tracks = glob.glob("assets/music/*.mp3")
    if not tracks:
        return None
    old_domain_terms = ("finance", "trading", "investment", "money")
    neutral_tracks = [
        t for t in tracks
        if not any(term in os.path.basename(t).lower() for term in old_domain_terms)
    ]
    return random.choice(neutral_tracks) if neutral_tracks else None


def run_assembler(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[assembler] Assembling video for {video_id}")

    manifest   = load_json(os.path.join(run_dir, "03b_scene_manifest.json"))
    voice_meta = load_json(os.path.join(run_dir, "03_voice_meta.json"))
    asset_meta = load_json(os.path.join(run_dir, "03_asset_meta.json"))

    voice_path     = os.path.join(run_dir, "03_voice.mp3")
    captions_path  = os.path.join(run_dir, "04_captions.ass")
    thumbnail_path = os.path.join(run_dir, "05_thumbnail.png")
    output_path    = os.path.join(run_dir, "06_final_video.mp4")

    fps           = config["video_fps"]
    xfade         = config["xfade_duration"]
    crf           = config["video_crf"]
    voice_duration = voice_meta["duration_sec"]
    end_hold = float(config.get("end_hold_sec", 0))
    cta_enabled = bool(config.get("cta_card_enabled", False))
    cta_duration = float(config.get("cta_card_duration_sec", 0)) if cta_enabled else 0.0

    segments_dir = os.path.join(run_dir, "segments")
    os.makedirs(segments_dir, exist_ok=True)

    # ── Thumbnail segment (optional static opening) ──────────────────────────
    thumb_duration = float(config.get("thumbnail_duration_sec", 0))
    opening_segments = []
    if thumb_duration > 0:
        print(f"[assembler] Creating thumbnail segment ({thumb_duration}s)")
        thumb_seg = os.path.join(segments_dir, "seg_thumb.mp4")
        _static_image_to_segment(thumbnail_path, thumb_duration, thumb_seg, fps)
        opening_segments.append((thumb_seg, thumb_duration))

    # ── Scene segments (dynamic) ──────────────────────────────────────────────
    scenes = manifest["scenes"]
    print(f"[assembler] Creating {len(scenes)} scene segments")
    scene_segs = []
    static_segment_count = (
        len(opening_segments)
        + (1 if end_hold > 0 else 0)
        + (1 if cta_duration > 0 else 0)
    )
    scene_durations = _compensate_scene_durations_for_xfade(scenes, static_segment_count, xfade)

    for i, scene in enumerate(scenes):
        sid      = scene["id"]
        duration = scene_durations[i]
        key      = f"scene_{sid}"
        asset    = asset_meta["assets"].get(key)
        seg_path = os.path.join(segments_dir, f"seg_scene_{sid}.mp4")

        if asset is None:
            print(f"[assembler] {key}: no asset found — using thumbnail fallback")
            _static_image_to_segment(thumbnail_path, duration, seg_path, fps)
        elif asset["type"] == "video":
            clip_path = os.path.join(run_dir, asset["path"])
            try:
                _clip_to_segment(clip_path, duration, seg_path, fps)
            except Exception as e:
                print(f"[assembler] {key} clip failed ({e}) — static fallback")
                _static_image_to_segment(thumbnail_path, duration, seg_path, fps)
        else:
            img_path = os.path.join(run_dir, asset["path"])
            try:
                _image_to_segment(img_path, duration, i, seg_path, fps)
            except Exception as e:
                print(f"[assembler] {key} Ken Burns failed ({e}) — static fallback")
                _static_image_to_segment(img_path, duration, seg_path, fps)

        scene_segs.append((seg_path, duration))
        print(f"[assembler] scene_{sid} done ({duration:.2f}s)")

    # ── End hold: optional static freeze of last scene after voice ends ──────
    if end_hold > 0 and scene_segs:
        print(f"[assembler] Creating end-hold segment ({end_hold}s)")
        # Use last scene's image as the hold frame
        last_scene = scenes[-1]
        last_key = f"scene_{last_scene['id']}"
        last_asset = asset_meta["assets"].get(last_key)
        hold_seg = os.path.join(segments_dir, "seg_hold.mp4")

        if last_asset and last_asset["type"] == "image":
            hold_src = os.path.join(run_dir, last_asset["path"])
            _static_image_to_segment(hold_src, end_hold, hold_seg, fps)
        else:
            # Video scene or missing — use thumbnail as hold frame
            _static_image_to_segment(thumbnail_path, end_hold, hold_seg, fps)

        scene_segs.append((hold_seg, end_hold))

    # ── Branded CTA card: short final logo/action beat for Shorts ────────────
    cta_segment_added = False
    if cta_duration > 0:
        print(f"[assembler] Creating CTA/logo card ({cta_duration}s)")
        cta_image = _create_cta_card(run_dir, config)
        cta_seg = os.path.join(segments_dir, "seg_cta_card.mp4")
        _static_image_to_segment(cta_image, cta_duration, cta_seg, fps)
        scene_segs.append((cta_seg, cta_duration))
        cta_segment_added = True

    # ── Concatenate ───────────────────────────────────────────────────────────
    all_segments = (
        opening_segments
        + scene_segs
    )
    print(f"[assembler] Concatenating {len(all_segments)} segments with xfade")
    concat_path = os.path.join(run_dir, "06_concat.mp4")
    _concat_with_xfade(all_segments, concat_path, fps, xfade)

    # ── Audio mix ─────────────────────────────────────────────────────────────
    music_track = _pick_music_track()
    total_video_duration = _xfaded_duration(all_segments, xfade)

    if music_track:
        print(f"[assembler] Mixing audio with {os.path.basename(music_track)}")
        mixed_audio_path = os.path.join(run_dir, "06_mixed_audio.aac")
        _mix_audio(voice_path, music_track, total_video_duration, mixed_audio_path,
                   config["voice_volume"], config["bg_music_volume"],
                   target_lufs=float(config.get("final_audio_lufs", -16)),
                   true_peak=float(config.get("final_audio_true_peak", -1.5)),
                   lra=float(config.get("final_audio_lra", 11)))
        audio_source = mixed_audio_path
    else:
        print(f"[assembler] No music tracks in assets/music/ — voice only")
        audio_source = voice_path

    # ── Captions + final render ───────────────────────────────────────────────
    print(f"[assembler] Burning captions and merging audio")
    film_overlay_applied = False
    try:
        film_overlay_applied = _assemble_final(concat_path, audio_source, captions_path, output_path, config, total_video_duration)
    except Exception as e:
        print(f"[assembler] Caption burn-in failed ({e}) — rendering without captions")
        film_overlay_applied = _assemble_without_captions(
            concat_path,
            audio_source,
            output_path,
            config,
            total_video_duration,
        )

    final_duration = _validate_final_video(output_path)

    meta = {
        "video_id": video_id,
        "final_duration_sec": final_duration,
        "resolution": "1080x1920",
        "codec": "h264",
        "fps": fps,
        "voice_duration_sec": voice_duration,
        "total_scenes": len(scenes),
        "segments": (
            (["thumbnail"] if opening_segments else [])
            + [f"scene_{s['id']}" for s in scenes]
            + (["hold"] if end_hold > 0 else [])
            + (["cta_card"] if cta_segment_added else [])
        ),
        "planned_visual_duration_sec": round(total_video_duration, 3),
        "audio_mix": {"voice": config["voice_volume"], "music": config["bg_music_volume"]},
        "captions": "04_captions.ass",
        "cta_card": {
            "enabled": cta_segment_added,
            "duration_sec": cta_duration if cta_segment_added else 0,
            "image": "06_cta_card.png" if cta_segment_added else "",
            "primary": config.get("cta_card_primary", ""),
            "secondary": config.get("cta_card_secondary", ""),
        },
        "film_overlay": {
            "requested": bool(config.get("film_overlay_enabled", False)),
            "applied": film_overlay_applied,
            "path": config.get("film_overlay_path", ""),
            "blend_mode": config.get("film_overlay_blend_mode", ""),
            "opacity": config.get("film_overlay_opacity", 0),
        },
        "music_track": os.path.basename(music_track) if music_track else "none",
        "validation": "passed",
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "06_render_meta.json"))
    print(f"[assembler] Done. Final video: {final_duration:.1f}s — {len(scenes)} scenes")
    return meta


# Mock reuses the real assembler — all steps are FFmpeg, no API calls needed
run_assembler_mock = run_assembler
