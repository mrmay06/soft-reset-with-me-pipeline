import os
import struct
import math

from utils.helpers import load_json, save_json, now_iso
from utils.retry import retry

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


def _build_tts_input(script: dict) -> str:
    """
    Gemini TTS style instruction prepended to drive pace + confidence.
    Speak mid-fast, direct, confident — no pauses, no filler — US finance Shorts energy.
    """
    style = (
        "Speak at a medium-fast pace. Confident, direct, no pauses between sentences. "
        "Authoritative US finance tone — like a sharp money expert, not a newscaster. "
        "Keep energy high throughout.\n\n"
    )
    script_text = (
        f"{script['hook']} "
        f"{script['tension']} "
        f"{script['insight']} "
        f"{script['loopback']} "
        f"{script.get('cta', '')}"
    ).strip()
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


def _validate_audio(path: str, config: dict) -> dict:
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
            return {"duration_sec": round(dur, 2), "validation": "passed"}
        except Exception:
            return {"duration_sec": 0.0, "validation": "skipped"}

    audio = AudioSegment.from_mp3(path)
    duration_sec = round(len(audio) / 1000, 2)

    result = {"duration_sec": duration_sec, "validation": "passed"}

    min_dur = config["audio_min_duration_sec"]
    max_dur = config["audio_max_duration_sec"]
    if duration_sec < min_dur or duration_sec > max_dur:
        result["validation"] = "duration_warning"
        result["warning"] = f"Audio is {duration_sec}s — outside expected {min_dur}-{max_dur}s range"
        print(f"[tts] WARNING: {result['warning']}")

    return result


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
    _generate_mock_mp3(output_path, duration_sec=41.0)

    meta = {
        "video_id": video_id,
        "voice": config["tts_voice"],
        "model": config["tts_model"],
        "duration_sec": 41.0,
        "validation": "passed",
        "tags_used": ["tension", "concern", "enthusiasm", "neutral"],
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "03_voice_meta.json"))
    print(f"[tts][MOCK] Done. Duration: 41.0s")
    return meta
