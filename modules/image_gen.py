from __future__ import annotations

import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone

import requests

from utils.helpers import load_json, now_iso, save_json
from utils.retry import retry

try:
    from PIL import Image
except ImportError:
    Image = None


CLIP_MEMORY_FILE = "clip_memory_soft_reset.json"
HARD_REUSE_DAYS = 30
SOFT_REUSE_DAYS = 90


def _sanitize_query(query: str) -> str:
    query = re.sub(
        r"\b(raccoons?|animals?|wildlife|cartoons?|mascots?|chibi|furry|fur|creature|anime)\b",
        "person",
        query or "",
        flags=re.IGNORECASE,
    )
    query = re.sub(r"[^A-Za-z0-9 ]+", " ", query)
    query = re.sub(r"\s+", " ", query).strip().lower()
    return query or "person alone room"


def _query_from_scene(scene: dict) -> str:
    if scene.get("pexels_query"):
        return _sanitize_query(scene["pexels_query"])
    prompt = str(scene.get("image_prompt") or scene.get("covers_dialogue") or "")
    prompt = re.sub(
        r"\b(editorial|cinematic|photorealistic|faceless|vertical|moody|lighting|palette|background)\b",
        " ",
        prompt,
        flags=re.IGNORECASE,
    )
    return _sanitize_query(" ".join(prompt.split()[:6]))


def _query_alternates(query: str) -> list[str]:
    base = _sanitize_query(query)
    words = set(base.split())
    choices = [base]
    groups = [
        ({"phone", "message", "texting", "reply"}, ["person checking phone", "phone in hand", "phone face down"]),
        ({"rain", "rainy", "window"}, ["person at window", "rain window", "apartment window"]),
        ({"walk", "walking", "city", "street"}, ["person walking alone", "city evening walk", "quiet street walking"]),
        ({"journal", "writing", "book"}, ["hands writing journal", "closing notebook", "person writing alone"]),
        ({"alone", "sad", "lonely", "room"}, ["person alone room", "pensive person indoors", "quiet apartment"]),
    ]
    for tokens, alternates in groups:
        if words & tokens:
            choices.extend(alternates)
    choices.extend(["pensive person", "quiet emotional moment"])
    deduped: list[str] = []
    for item in choices:
        item = _sanitize_query(item)
        if item not in deduped:
            deduped.append(item)
    return deduped[:5]


def _load_clip_memory(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    data = load_json(path)
    return data if isinstance(data, list) else []


def _age_days(value: str) -> int:
    try:
        used = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0, (datetime.now(timezone.utc) - used).days)
    except Exception:
        return 9999


def _recent_ids(memory: list[dict], provider: str, days: int) -> set[str]:
    return {
        str(item.get("provider_id"))
        for item in memory
        if item.get("provider") == provider and _age_days(str(item.get("used_at", ""))) <= days
    }


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _pexels_candidates(query: str, per_page: int = 20) -> list[dict]:
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set")
    response = requests.get(
        "https://api.pexels.com/videos/search",
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": per_page},
        timeout=25,
    )
    response.raise_for_status()
    candidates = []
    for rank, video in enumerate(response.json().get("videos", [])):
        files = [item for item in video.get("video_files", []) if item.get("link") and item.get("width") and item.get("height")]
        if not files:
            continue
        source = min(files, key=lambda item: abs(int(item["width"]) - 1080))
        candidates.append({
            "provider": "pexels",
            "provider_id": str(video.get("id", "")),
            "source_url": source["link"],
            "preview_url": video.get("image", ""),
            "width": int(source["width"]),
            "height": int(source["height"]),
            "duration": float(video.get("duration") or 0),
            "creator": str((video.get("user") or {}).get("id", "")),
            "query": query,
            "rank": rank,
        })
    return candidates


def _candidate_score(candidate: dict, used_creators: set[str], soft_recent: set[str]) -> float:
    score = 100.0 - float(candidate["rank"]) * 1.5
    if candidate["height"] > candidate["width"]:
        score += 12
    if candidate["width"] >= 720:
        score += 5
    if 4 <= candidate["duration"] <= 20:
        score += 4
    if candidate["creator"] and candidate["creator"] in used_creators:
        score -= 10
    if candidate["provider_id"] in soft_recent:
        score -= 30
    return score


def _build_pools(scenes: list[dict], memory: list[dict], config: dict) -> dict[int, list[dict]]:
    hard_recent = _recent_ids(memory, "pexels", int(config.get("clip_reuse_hard_block_days", HARD_REUSE_DAYS)))
    pools: dict[int, list[dict]] = {}
    cache: dict[str, list[dict]] = {}
    for scene in scenes:
        query = _query_from_scene(scene)
        candidates: list[dict] = []
        for alternate in _query_alternates(query)[:3]:
            if alternate not in cache:
                cache[alternate] = _pexels_candidates(alternate, int(config.get("clip_candidate_pool_size", 20)))
            candidates.extend(cache[alternate])
            if len({item["provider_id"] for item in candidates}) >= 12:
                break
        deduped = {item["provider_id"]: item for item in candidates if item["provider_id"] not in hard_recent}
        pools[int(scene["id"])] = list(deduped.values())
    return pools


def _assign_globally(scenes: list[dict], pools: dict[int, list[dict]], memory: list[dict], config: dict) -> dict[int, list[dict]]:
    soft_recent = _recent_ids(memory, "pexels", int(config.get("clip_reuse_soft_penalty_days", SOFT_REUSE_DAYS)))
    used_ids: set[str] = set()
    used_creators: set[str] = set()
    ranked: dict[int, list[dict]] = {}
    for scene in scenes:
        scene_id = int(scene["id"])
        available = [item for item in pools.get(scene_id, []) if item["provider_id"] not in used_ids]
        available.sort(key=lambda item: (-_candidate_score(item, used_creators, soft_recent), item["provider_id"]))
        if not available:
            raise RuntimeError(f"Clip-only selection failed: no unique candidate for scene {scene_id}")
        ranked[scene_id] = available
        chosen = available[0]
        used_ids.add(chosen["provider_id"])
        if chosen["creator"]:
            used_creators.add(chosen["creator"])
    return ranked


def _frame_hash(video_path: str, frame_path: str) -> str:
    if Image is None:
        return ""
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "0.5", "-i", video_path, "-frames:v", "1", frame_path],
        check=True,
        capture_output=True,
    )
    image = Image.open(frame_path).convert("L").resize((8, 8))
    pixels = list(image.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _hash_distance(left: str, right: str) -> int:
    if not left or not right:
        return 999
    return bin(int(left, 16) ^ int(right, 16)).count("1")


@retry(max_attempts=2, wait_seconds=5, exceptions=(Exception,))
def _download(candidate: dict, output_path: str) -> str:
    response = requests.get(candidate["source_url"], timeout=90)
    response.raise_for_status()
    if len(response.content) < 50_000:
        raise RuntimeError("Downloaded clip is too small")
    with open(output_path, "wb") as handle:
        handle.write(response.content)
    return hashlib.sha256(response.content).hexdigest()


def run_image_gen(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[clip_selector] Selecting clip-only assets for {video_id}")
    manifest = load_json(os.path.join(run_dir, "03b_scene_manifest.json"))
    scenes = manifest.get("scenes", [])
    if not scenes:
        raise RuntimeError("Clip-only selection requires at least one scene")
    assets_dir = os.path.join(run_dir, "03_images")
    os.makedirs(assets_dir, exist_ok=True)
    memory_path = config.get("clip_memory_file", CLIP_MEMORY_FILE)
    memory = _load_clip_memory(memory_path)
    pools = _build_pools(scenes, memory, config)
    ranked = _assign_globally(scenes, pools, memory, config)

    results: dict[str, dict] = {}
    used_hashes: set[str] = set()
    used_frame_hashes: list[str] = []
    used_provider_ids: set[str] = set()
    hard_days = int(config.get("clip_reuse_hard_block_days", HARD_REUSE_DAYS))
    remembered_hashes = {
        str(item.get("file_hash")) for item in memory
        if item.get("file_hash") and _age_days(str(item.get("used_at", ""))) <= hard_days
    }
    remembered_frame_hashes = [
        str(item.get("perceptual_hash")) for item in memory
        if item.get("perceptual_hash") and _age_days(str(item.get("used_at", ""))) <= hard_days
    ]
    hash_distance = int(config.get("clip_perceptual_hash_distance", 5))
    new_memory: list[dict] = []
    for scene in scenes:
        scene_id = int(scene["id"])
        output_path = os.path.join(assets_dir, f"scene_{scene_id}.mp4")
        selected = None
        for candidate in ranked[scene_id]:
            if candidate["provider_id"] in used_provider_ids:
                continue
            file_hash = _download(candidate, output_path)
            frame_path = os.path.join(assets_dir, f"scene_{scene_id}_preview.jpg")
            perceptual_hash = _frame_hash(output_path, frame_path)
            if (
                file_hash in used_hashes
                or file_hash in remembered_hashes
                or any(_hash_distance(perceptual_hash, prior) <= hash_distance for prior in used_frame_hashes)
                or any(_hash_distance(perceptual_hash, prior) <= hash_distance for prior in remembered_frame_hashes)
            ):
                continue
            selected = candidate
            used_hashes.add(file_hash)
            used_frame_hashes.append(perceptual_hash)
            used_provider_ids.add(candidate["provider_id"])
            break
        if selected is None:
            raise RuntimeError(f"Clip-only selection failed: all candidates for scene {scene_id} were duplicate footage")
        rel_path = os.path.relpath(output_path, start=run_dir)
        results[f"scene_{scene_id}"] = {
            "type": "video",
            "source": selected["provider"],
            "path": rel_path,
            "provider_id": selected["provider_id"],
            "source_url": selected["source_url"],
            "query": selected["query"],
            "file_hash": file_hash,
            "perceptual_hash": perceptual_hash,
            "selection_score": _candidate_score(selected, set(), set()),
        }
        new_memory.append({
            "provider": selected["provider"],
            "provider_id": selected["provider_id"],
            "source_url": selected["source_url"],
            "file_hash": file_hash,
            "perceptual_hash": perceptual_hash,
            "query": selected["query"],
            "video_id": video_id,
            "scene_id": scene_id,
            "used_at": now_iso(),
        })
        print(f"[clip_selector] scene_{scene_id}: Pexels {selected['provider_id']} ({selected['query']})")

    save_json((memory + new_memory)[-1000:], memory_path)
    meta = {
        "video_id": video_id,
        "assets": results,
        "total_scenes": len(scenes),
        "video_count": len(results),
        "fallback_count": 0,
        "selection_strategy": "global_clip_only_v1",
        "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "03_asset_meta.json"))
    return meta


def _make_mock_clip(path: str, label: str, duration: float = 4.0) -> None:
    safe_label = re.sub(r"[^A-Za-z0-9 _-]", "", label)[:30] or "SCENE"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x1C1C2B:s=1080x1920:d={duration}",
            "-vf", f"drawtext=text='{safe_label}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2",
            "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", path,
        ],
        check=True,
        capture_output=True,
    )


def run_image_gen_mock(video_id: str, run_dir: str, config: dict) -> dict:
    manifest = load_json(os.path.join(run_dir, "03b_scene_manifest.json"))
    assets_dir = os.path.join(run_dir, "03_images")
    os.makedirs(assets_dir, exist_ok=True)
    results = {}
    for scene in manifest.get("scenes", []):
        scene_id = int(scene["id"])
        output_path = os.path.join(assets_dir, f"scene_{scene_id}.mp4")
        _make_mock_clip(output_path, f"SCENE {scene_id}")
        results[f"scene_{scene_id}"] = {
            "type": "video", "source": "mock", "path": os.path.relpath(output_path, start=run_dir),
            "provider_id": f"mock-{scene_id}", "query": "mock",
        }
    meta = {
        "video_id": video_id, "assets": results, "total_scenes": len(results),
        "video_count": len(results), "fallback_count": 0,
        "selection_strategy": "mock_clip_only", "generated_at": now_iso(),
    }
    save_json(meta, os.path.join(run_dir, "03_asset_meta.json"))
    return meta
