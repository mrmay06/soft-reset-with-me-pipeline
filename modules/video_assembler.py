import os
import json
import re
import random
import subprocess
import glob

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


def _build_drawtext_filter(ass_path: str, font_path: str = "assets/fonts/Montserrat-ExtraBold.ttf") -> str:
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
            f"fontsize=78:"
            f"fontcolor=white:"
            f"borderw=4:"
            f"bordercolor=black:"
            f"x=(w-text_w)/2:"
            f"y=h-620:"
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


def _calculate_beat_durations(script: dict, voice_duration: float) -> dict:
    insight_words = script["insight"].split()
    insight_half = len(insight_words) / 2

    sections = {
        "beat_1": len(script["hook"].split()),
        "beat_2": len(script["tension"].split()),
        "beat_3": insight_half,
        "beat_4": insight_half,
        "beat_5": len(script["loopback"].split()) + len(script.get("cta", "").split()),
    }
    total_words = sum(sections.values())
    durations = {}
    for beat, word_count in sections.items():
        ratio = word_count / total_words
        durations[beat] = max(2.0, round(voice_duration * ratio, 2))
    return durations


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
        "-vf", f"scale=8000:-1,{zoompan},scale=1080:1920",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], f"image_to_segment:{output_path}")


def _clip_to_segment(clip_path: str, duration: float, output_path: str, fps: int = 30):
    _run_ffmpeg([
        "ffmpeg", "-stream_loop", "-1", "-i", clip_path,
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps), "-an", output_path, "-y"
    ], f"clip_to_segment:{output_path}")


def _static_image_to_segment(image_path: str, duration: float, output_path: str, fps: int = 30):
    _run_ffmpeg([
        "ffmpeg", "-loop", "1", "-i", image_path,
        "-t", str(duration),
        "-vf", "scale=1080:1920",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], f"static_to_segment:{output_path}")


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
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(fps), output_path, "-y"
    ], "concat_xfade")


def _mix_audio(voice_path: str, music_path: str, total_duration: float, output_path: str,
               voice_vol: float = 1.0, music_vol: float = 0.13, fade_out_sec: float = 2.0):
    fade_start = max(0, total_duration - fade_out_sec)
    _run_ffmpeg([
        "ffmpeg",
        "-i", voice_path,
        "-stream_loop", "-1", "-i", music_path,
        "-t", str(total_duration),
        "-filter_complex",
        (
            f"[0:a]volume={voice_vol}[voice];"
            f"[1:a]volume={music_vol},atrim=0:{total_duration},"
            f"afade=t=out:st={fade_start:.3f}:d={fade_out_sec}[music];"
            f"[voice][music]amix=inputs=2:duration=first[aout]"
        ),
        "-map", "[aout]",
        "-c:a", "aac", "-ar", "44100",
        output_path, "-y"
    ], "mix_audio")


def _assemble_final(video_path: str, audio_path: str, captions_path: str, output_path: str, crf: int = 23):
    base_cmd = [
        "ffmpeg",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-crf", str(crf),
        "-c:a", "aac", "-ar", "44100",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-movflags", "+faststart",
    ]

    if _has_libass():
        # Best path: full karaoke ASS burn-in
        abs_captions = os.path.abspath(captions_path)
        safe_captions = abs_captions.replace("'", "\\'").replace("\\", "/")
        abs_fonts = os.path.abspath("assets/fonts").replace("\\", "/")
        vf = f"ass='{safe_captions}':fontsdir='{abs_fonts}'"
        caption_method = "ass (libass)"
    else:
        # Fallback: drawtext chain parsed from ASS timing data
        vf = _build_drawtext_filter(captions_path)
        caption_method = "drawtext (libass fallback)"

    print(f"[assembler] Caption method: {caption_method}")
    _run_ffmpeg(base_cmd + ["-vf", vf, output_path, "-y"], "assemble_final")


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
    return random.choice(tracks)


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

    segments_dir = os.path.join(run_dir, "segments")
    os.makedirs(segments_dir, exist_ok=True)

    # ── Thumbnail segment (static) ────────────────────────────────────────────
    print(f"[assembler] Creating thumbnail segment ({config['thumbnail_duration_sec']}s)")
    thumb_seg = os.path.join(segments_dir, "seg_thumb.mp4")
    _static_image_to_segment(thumbnail_path, config["thumbnail_duration_sec"], thumb_seg, fps)

    # ── Scene segments (dynamic) ──────────────────────────────────────────────
    scenes = manifest["scenes"]
    print(f"[assembler] Creating {len(scenes)} scene segments")
    scene_segs = []

    for i, scene in enumerate(scenes):
        sid      = scene["id"]
        duration = scene.get("duration_sec", 3.0)
        duration = max(1.5, duration)
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

    # ── End hold — 2s static freeze of last scene after voice ends ───────────
    end_hold = config.get("end_hold_sec", 2)
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

    # ── Disclaimer segment — ALWAYS use branded static asset ────────────────
    disc_src = os.path.abspath("assets/disclaimer.png")
    if not os.path.exists(disc_src):
        raise FileNotFoundError(f"Branded disclaimer image missing at {disc_src}")
    print(f"[assembler] Creating disclaimer segment ({config['disclaimer_duration_sec']}s) — {disc_src}")
    disclaimer_seg = os.path.join(segments_dir, "seg_disclaimer.mp4")
    _static_image_to_segment(disc_src, config["disclaimer_duration_sec"], disclaimer_seg, fps)

    # ── Concatenate ───────────────────────────────────────────────────────────
    all_segments = (
        [(thumb_seg, config["thumbnail_duration_sec"])]
        + scene_segs
        + [(disclaimer_seg, config["disclaimer_duration_sec"])]
    )
    print(f"[assembler] Concatenating {len(all_segments)} segments with xfade")
    concat_path = os.path.join(run_dir, "06_concat.mp4")
    _concat_with_xfade(all_segments, concat_path, fps, xfade)

    # ── Audio mix ─────────────────────────────────────────────────────────────
    music_track = _pick_music_track()
    total_video_duration = (voice_duration + config["thumbnail_duration_sec"]
                            + config.get("end_hold_sec", 2) + config["disclaimer_duration_sec"])

    if music_track:
        print(f"[assembler] Mixing audio with {os.path.basename(music_track)}")
        mixed_audio_path = os.path.join(run_dir, "06_mixed_audio.aac")
        _mix_audio(voice_path, music_track, total_video_duration, mixed_audio_path,
                   config["voice_volume"], config["bg_music_volume"])
        audio_source = mixed_audio_path
    else:
        print(f"[assembler] No music tracks in assets/music/ — voice only")
        audio_source = voice_path

    # ── Captions + final render ───────────────────────────────────────────────
    print(f"[assembler] Burning captions and merging audio")
    try:
        _assemble_final(concat_path, audio_source, captions_path, output_path, crf)
    except Exception as e:
        print(f"[assembler] Caption burn-in failed ({e}) — rendering without captions")
        _run_ffmpeg([
            "ffmpeg", "-i", concat_path, "-i", audio_source,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-crf", str(crf), "-c:a", "aac",
            "-movflags", "+faststart", output_path, "-y"
        ], "assemble_no_captions")

    final_duration = _validate_final_video(output_path)

    meta = {
        "video_id": video_id,
        "final_duration_sec": final_duration,
        "resolution": "1080x1920",
        "codec": "h264",
        "fps": fps,
        "total_scenes": len(scenes),
        "segments": ["thumbnail"] + [f"scene_{s['id']}" for s in scenes] + ["disclaimer"],
        "audio_mix": {"voice": config["voice_volume"], "music": config["bg_music_volume"]},
        "captions": "04_captions.ass",
        "music_track": os.path.basename(music_track) if music_track else "none",
        "validation": "passed",
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "06_render_meta.json"))
    print(f"[assembler] Done. Final video: {final_duration:.1f}s — {len(scenes)} scenes")
    return meta


# Mock reuses the real assembler — all steps are FFmpeg, no API calls needed
run_assembler_mock = run_assembler
