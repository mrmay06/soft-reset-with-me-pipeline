"""Keep the rendered thumbnail selection and its publishing metadata together."""
from pathlib import Path
from time import time_ns

from utils.helpers import load_json, save_json


def selected_package(metadata: dict, thumbnail_meta: dict) -> dict:
    primary_id = thumbnail_meta.get("primary_variant_id")
    rendered = next((item for item in thumbnail_meta.get("variants", [])
                     if item.get("id") == primary_id), None)
    title = next((item for item in metadata.get("title_variants", [])
                  if item.get("id") == primary_id), None)
    if not rendered or rendered.get("valid") is not True:
        raise RuntimeError("Selected long-form thumbnail has no valid rendered variant")
    if not title or not str(title.get("title", "")).strip():
        raise RuntimeError(f"Selected thumbnail {primary_id} has no matching title")
    if not rendered.get("output_file") or not rendered.get("prompt_file"):
        raise RuntimeError("Selected thumbnail is missing its image or prompt reference")
    return {
        "primary_variant_id": primary_id,
        "title": title["title"],
        "thumbnail_text": rendered.get("thumbnail_text", ""),
        "primary_thumbnail_output_file": rendered["output_file"],
        "primary_thumbnail_prompt_file": rendered["prompt_file"],
    }


def validate_package_files(run_dir: str, package: dict) -> None:
    root = Path(run_dir)
    selected = root / package["primary_thumbnail_output_file"]
    final = root / "07_longform_thumbnail.png"
    prompt = root / package["primary_thumbnail_prompt_file"]
    if not selected.is_file() or not final.is_file() or not prompt.is_file():
        raise RuntimeError("Selected thumbnail image or prompt file is missing")
    if selected.read_bytes() != final.read_bytes():
        raise RuntimeError("Upload thumbnail does not match the selected rendered variant")


def synchronize_longform_packaging(run_dir: str) -> bool:
    """Also runs on resume, before judging; return whether the package changed."""
    root = Path(run_dir)
    metadata = load_json(str(root / "03_longform_metadata.json"))
    thumbnail_meta = load_json(str(root / "07_longform_thumbnail_meta.json"))
    package = selected_package(metadata, thumbnail_meta)
    validate_package_files(run_dir, package)
    if all(metadata.get(key) == value for key, value in package.items()):
        return False
    # A resumed run must not reuse approval for the old title/thumbnail pair,
    # even if the fresh judging attempt fails after metadata has been saved.
    judge = root / "10_judge_report.json"
    if judge.exists():
        judge.replace(root / f"10_judge_report_before_packaging_sync_{time_ns()}.json")
    metadata.setdefault("requested_primary_variant_id", metadata.get("primary_variant_id"))
    metadata.update(package)
    save_json(metadata, str(root / "03_longform_metadata.json"))
    print(f"[longform_packaging] Title, thumbnail, and prompt synchronized to {package['primary_variant_id']}")
    return True


def require_synchronized_packaging(run_dir: str, metadata: dict) -> None:
    thumbnail_meta = load_json(str(Path(run_dir) / "07_longform_thumbnail_meta.json"))
    package = selected_package(metadata, thumbnail_meta)
    if any(metadata.get(key) != value for key, value in package.items()):
        raise RuntimeError("Long-form packaging mismatch; synchronize and rejudge before upload")
    validate_package_files(run_dir, package)
