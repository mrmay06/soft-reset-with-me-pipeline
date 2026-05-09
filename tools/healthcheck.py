from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {"venv", "workspace", "__pycache__", ".git"}
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def _project_files(pattern: str) -> list[Path]:
    return [
        path for path in ROOT.rglob(pattern)
        if not any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)
    ]


def _check_python_ast() -> list[str]:
    errors: list[str] = []
    for path in _project_files("*.py"):
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}: syntax error line {exc.lineno}: {exc.msg}")
    return errors


def _check_json_files() -> list[str]:
    errors: list[str] = []
    for path in _project_files("*.json"):
        text = path.read_text()
        for marker in CONFLICT_MARKERS:
            if marker in text:
                errors.append(f"{path.relative_to(ROOT)}: contains merge conflict marker {marker!r}")
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid JSON line {exc.lineno}, col {exc.colno}: {exc.msg}")
    return errors


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _check_memory_files() -> list[str]:
    errors: list[str] = []
    configs = [
        (ROOT / "config" / "pipeline_config.json", "topic_memory_soft_reset.json", "performance_memory_soft_reset.json"),
        (ROOT / "config" / "longform_config.json", "topic_memory_soft_reset_long.json", "performance_memory_soft_reset_long.json"),
    ]
    for config_path, topic_fallback, performance_fallback in configs:
        config = _load_json(config_path)
        for key, fallback in (
            ("topic_memory_file", topic_fallback),
            ("performance_memory_file", performance_fallback),
        ):
            path = ROOT / config.get(key, fallback)
            if not path.exists():
                continue
            data = json.loads(path.read_text())
            if not isinstance(data, (list, dict)):
                errors.append(f"{path.relative_to(ROOT)}: expected JSON array or object")
                continue
            rows = data if isinstance(data, list) else data.get("videos", [])
            if not isinstance(rows, list):
                continue
            seen: set[str] = set()
            duplicates: set[str] = set()
            for item in rows:
                if not isinstance(item, dict):
                    continue
                video_id = item.get("video_id")
                if not video_id:
                    continue
                if video_id in seen:
                    duplicates.add(str(video_id))
                seen.add(str(video_id))
            if duplicates:
                errors.append(f"{path.relative_to(ROOT)}: duplicate video_id values: {', '.join(sorted(duplicates))}")
    return errors


def _check_strategy_promotion_gate() -> list[str]:
    path = ROOT / "tools" / "weekly_strategy.py"
    if not path.exists():
        return []
    text = path.read_text()
    blocked = ("copy(REVIEWED", "copyfile(REVIEWED", "shutil.copy")
    if any(token in text for token in blocked):
        return ["tools/weekly_strategy.py: weekly strategy appears to promote active strategy directly"]
    return []


def main() -> int:
    checks = {
        "python_ast": _check_python_ast(),
        "json": _check_json_files(),
        "memory": _check_memory_files(),
        "strategy_gate": _check_strategy_promotion_gate(),
    }
    errors = [error for group in checks.values() for error in group]
    if errors:
        for name, group in checks.items():
            if group:
                print(f"[healthcheck] {name}: FAIL")
                for error in group:
                    print(f"  - {error}")
        return 1

    print("[healthcheck] OK")
    print(f"  Python files: {len(_project_files('*.py'))}")
    print(f"  JSON files:   {len(_project_files('*.json'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
