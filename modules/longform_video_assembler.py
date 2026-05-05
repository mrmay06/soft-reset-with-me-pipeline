from __future__ import annotations

import glob
import json
import os
import random
import subprocess

from PIL import Image, ImageDraw, ImageFont

from utils.helpers import load_json, save_json, now_iso
from utils.script_contract import word_count
from modules.video_assembler import _mix_audio


def _run_ffmpeg(cmd: list[str], label: str):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"[longform_video] FFmpeg failed ({label}):\n{result.stderr[-1200:]}")


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
    assert duration >= 240, f"Long-form render too short: {duration}"
    return {
        "duration_sec": round(duration, 2),
        "width": stream["width"],
        "height": stream["height"],
        "codec": stream["codec_name"],
    }


def run_longform_video(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_video] Rendering long-form video for {video_id}")
    research = load_json(os.path.join(run_dir, "01_longform_research.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    voice_meta = load_json(os.path.join(run_dir, "04_longform_voice_meta.json"))
    voice_path = os.path.join(run_dir, "04_longform_voice.mp3")

    chapters = script.get("chapters", [])
    total_words = max(1, sum(word_count(ch.get("voiceover", "")) for ch in chapters))
    total_duration = float(voice_meta["duration_sec"])

    render_dir = os.path.join(run_dir, "longform_render")
    os.makedirs(render_dir, exist_ok=True)

    segments = []
    for idx, chapter in enumerate(chapters):
        chapter_words = max(1, word_count(chapter.get("voiceover", "")))
        duration = max(12.0, total_duration * chapter_words / total_words)
        card = os.path.join(render_dir, f"chapter_{idx + 1:02d}.png")
        seg = os.path.join(render_dir, f"chapter_{idx + 1:02d}.mp4")
        _chapter_card(chapter, idx, len(chapters), metadata, research, card, config)
        _image_segment(card, duration, seg, config)
        segments.append(seg)
        print(f"[longform_video] chapter_{idx + 1:02d} segment {duration:.1f}s")

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
    crf = int(config.get("longform_crf", 23))
    fps = int(config.get("longform_fps", 30))
    _run_ffmpeg([
        "ffmpeg", "-i", concat_path, "-i", audio_source,
        "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-c:a", "aac", "-ar", "44100",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-movflags", "+faststart",
        "-t", str(total_duration),
        output_path, "-y"
    ], "final_mux")

    validation = _validate_video(output_path, config)
    meta = {
        "video_id": video_id,
        "output": "06_longform_video.mp4",
        "chapters": len(chapters),
        "music_track": os.path.basename(music) if music else "none",
        "validation": "passed",
        "generated_at": now_iso(),
        **validation,
    }
    save_json(meta, os.path.join(run_dir, "06_longform_render_meta.json"))
    print(f"[longform_video] Done. Final video: {validation['duration_sec']}s")
    return meta


run_longform_video_mock = run_longform_video
