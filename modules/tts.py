import os
import struct
import math

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry
from utils.script_contract import build_spoken_script_text

try:
    from google import genai as _genai
    from google.genai import types as _genai_types
except ImportError:
    _genai = None
    _genai_types = None

try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None


def _remove_duplicate_sentences(text: str) -> str:
    """
    Remove duplicate or near-duplicate consecutive sentences from joined script text.
    Catches cases where the LLM repeats a closing sentence at the start of the next section.
    """
    import re
    # Split into sentences
    raw = re.split(r'(?<=[.!?,—])\s+', text.strip())
    sentences = [s.strip() for s in raw if s.strip()]

    seen = []
    for s in sentences:
        # Normalise for comparison: lowercase, strip punctuation
        norm = re.sub(r'[^a-z0-9 ]', '', s.lower()).strip()
        # Skip if this sentence is identical or near-identical to the previous one
        if seen and norm == re.sub(r'[^a-z0-9 ]', '', seen[-1].lower()).strip():
            continue
        # Skip if this sentence is a substring of the previous (trailing fragment)
        if seen and len(norm) > 10 and norm in re.sub(r'[^a-z0-9 ]', '', seen[-1].lower()):
            continue
        seen.append(s)

    return " ".join(seen)


def _build_tts_input(script: dict) -> str:
    """
    Gemini TTS style instruction prepended to drive pace + energy.
    Warm honest-friend narration — calm, hushed, direct, never preachy.
    """
    style = (
        "Warm, calm, slightly hushed honest friend. Not a therapist, not a guru, not a hype coach. "
        "Confident, conversational, direct, and gentle. Speak a little fast, with tight gaps between sentences. "
        "Never sound robotic, preachy, overly energetic, or clinical. "
        "Short sentences should feel like something the listener needed to hear.\n\n"
    )
    script_text = build_spoken_script_text(script)
    # Replace em-dashes with comma-pause so TTS reads naturally
    script_text = script_text.replace("—", ",").replace("--", ",")
    # Remove duplicate trailing sentences from section joins
    script_text = _remove_duplicate_sentences(script_text)
    return style + script_text


@retry(max_attempts=3, wait_seconds=60, exceptions=(Exception,))
def _call_gemini_tts(tts_input: str, config: dict, output_path: str):
    if _genai is None:
        raise RuntimeError("google-genai not installed — run: pip install google-genai")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=config["tts_model"],
        contents=tts_input,
        config=_genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=_genai_types.SpeechConfig(
                voice_config=_genai_types.VoiceConfig(
                    prebuilt_voice_config=_genai_types.PrebuiltVoiceConfig(
                        voice_name=config["tts_voice"]
                    )
                )
            )
        )
    )

    part = response.candidates[0].content.parts[0]
    audio_data = part.inline_data.data
    mime_type  = part.inline_data.mime_type   # e.g. "audio/L16;rate=24000" (raw PCM)

    if not audio_data:
        raise ValueError("TTS returned empty audio data")

    # Gemini TTS returns raw PCM (audio/L16) — wrap in WAV then convert to MP3
    import wave, subprocess, tempfile

    wav_path = output_path.replace(".mp3", "_tts_raw.wav")
    sample_rate = 24000
    # Extract rate from mime_type if present (e.g. "audio/L16;rate=24000")
    if "rate=" in (mime_type or ""):
        try:
            sample_rate = int(mime_type.split("rate=")[1].split(";")[0])
        except Exception:
            pass

    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)      # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_data)

    # Convert WAV → MP3, trim any leading silence so voice hits frame zero
    trimmed_path = output_path.replace(".mp3", "_notrim.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path,
         "-acodec", "libmp3lame", "-ar", str(sample_rate), "-q:a", "2",
         trimmed_path],
        check=True, capture_output=True
    )
    os.remove(wav_path)

    # Remove leading silence (threshold -50dB, max 0.3s trim)
    subprocess.run(
        ["ffmpeg", "-y", "-i", trimmed_path,
         "-af", "silenceremove=start_periods=1:start_duration=0.05:start_threshold=-50dB",
         "-acodec", "libmp3lame", "-q:a", "2",
         output_path],
        check=True, capture_output=True
    )
    os.remove(trimmed_path)

    speed = float(config.get("tts_speed", 1.0))
    if speed and abs(speed - 1.0) > 0.01:
        sped_path = output_path.replace(".mp3", "_speed.mp3")
        subprocess.run(
            ["ffmpeg", "-y", "-i", output_path,
             "-filter:a", f"atempo={max(0.5, min(2.0, speed))}",
             "-acodec", "libmp3lame", "-q:a", "2",
             sped_path],
            check=True, capture_output=True
        )
        os.replace(sped_path, output_path)


def _validate_audio(path: str, config: dict) -> dict:
    def _duration_result(duration_sec: float) -> dict:
        result = {"duration_sec": round(duration_sec, 2), "validation": "passed"}
        min_dur = config["audio_min_duration_sec"]
        max_dur = config["audio_max_duration_sec"]
        if duration_sec < min_dur or duration_sec > max_dur:
            result["validation"] = "duration_warning"
            result["warning"] = f"Audio is {round(duration_sec, 2)}s — outside expected {min_dur}-{max_dur}s range"
            print(f"[tts] WARNING: {result['warning']}")
        return result

    if AudioSegment is None:
        # Fallback: use ffprobe to get duration
        import subprocess, json as _json
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "json", path],
                capture_output=True, text=True, check=True
            )
            dur = float(_json.loads(r.stdout)["format"]["duration"])
            return _duration_result(dur)
        except Exception:
            return {"duration_sec": 0.0, "validation": "skipped"}

    audio = AudioSegment.from_mp3(path)
    duration_sec = round(len(audio) / 1000, 2)
    return _duration_result(duration_sec)


def run_tts(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[tts] Generating voiceover for {video_id}")

    script = load_json(os.path.join(run_dir, "02_script.json"))
    tts_input = _build_tts_input(script)
    output_path = os.path.join(run_dir, "03_voice.mp3")

    _call_gemini_tts(tts_input, config, output_path)
    validation = _validate_audio(output_path, config)

    meta = {
        "video_id": video_id,
        "voice": config["tts_voice"],
        "model": config["tts_model"],
        "duration_sec": validation["duration_sec"],
        "validation": validation["validation"],
        "tags_used": ["tension", "concern", "enthusiasm", "neutral"],
        "generated_at": now_iso(),
    }
    if "warning" in validation:
        meta["warning"] = validation["warning"]

    save_json(meta, os.path.join(run_dir, "03_voice_meta.json"))
    print(f"[tts] Done. Duration: {meta['duration_sec']}s, validation: {meta['validation']}")
    return meta


def _generate_mock_mp3(path: str, duration_sec: float = 40.0):
    """Generate a minimal valid MP3 file using a sine wave encoded as PCM WAV first."""
    sample_rate = 24000
    frequency = 440
    num_samples = int(sample_rate * duration_sec)

    # Build WAV bytes in memory
    wav_path = path.replace(".mp3", "_temp.wav")
    with open(wav_path, "wb") as f:
        num_channels = 1
        bits_per_sample = 16
        byte_rate = sample_rate * num_channels * bits_per_sample // 8
        block_align = num_channels * bits_per_sample // 8
        data_size = num_samples * block_align

        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))
        f.write(struct.pack("<H", 1))       # PCM
        f.write(struct.pack("<H", num_channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))

        for i in range(num_samples):
            amplitude = 0.3
            sample = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * i / sample_rate))
            f.write(struct.pack("<h", sample))

    # Convert WAV to MP3 using ffmpeg
    import subprocess
    subprocess.run(
        ["ffmpeg", "-y", "-i", wav_path, "-acodec", "libmp3lame", "-ar", "24000", path],
        check=True, capture_output=True
    )
    os.remove(wav_path)


def run_tts_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[tts][MOCK] Generating mock audio for {video_id}")

    output_path = os.path.join(run_dir, "03_voice.mp3")
    duration_sec = 26.0
    _generate_mock_mp3(output_path, duration_sec=duration_sec)

    meta = {
        "video_id": video_id,
        "voice": config["tts_voice"],
        "model": config["tts_model"],
        "duration_sec": duration_sec,
        "validation": "passed",
        "tags_used": ["tension", "concern", "enthusiasm", "neutral"],
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "03_voice_meta.json"))
    print(f"[tts][MOCK] Done. Duration: {duration_sec}s")
    return meta
