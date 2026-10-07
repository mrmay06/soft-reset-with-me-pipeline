"""Publish only changed production memory, without staging runner outputs.

Use a temporary worktree based on the latest remote branch so simultaneous
Shorts, long-form, and strategy commits do not discard each other's changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile


MEMORY_FILES = {
    "short": (
        "topic_memory_soft_reset.json",
        "performance_memory_soft_reset.json",
        "clip_memory_soft_reset.json",
    ),
    "long": (
        "topic_memory_soft_reset_long.json",
        "performance_memory_soft_reset_long.json",
        "clip_memory_soft_reset_long.json",
    ),
}


def git(root: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def persist(root: Path, track: str, branch: str, attempts: int = 3) -> bool:
    git(root, "check-ref-format", "--branch", branch)
    changed = {}
    for name in MEMORY_FILES[track]:
        path = root / name
        if not path.exists():
            continue
        content = path.read_bytes()
        baseline = git(root, "show", f"HEAD:{name}", check=False)
        if baseline.returncode == 0 and baseline.stdout == content:
            continue
        # Fail before making any commit if a writer left incomplete JSON.
        json.loads(content)
        changed[name] = content
    if not changed:
        print("No production memory changes to save.")
        return False

    for attempt in range(attempts):
        git(root, "fetch", "origin", f"refs/heads/{branch}")
        with tempfile.TemporaryDirectory(prefix="pipeline-memory-") as directory:
            worktree = Path(directory) / "checkout"
            git(root, "worktree", "add", "--detach", str(worktree), "FETCH_HEAD")
            try:
                for name, content in changed.items():
                    (worktree / name).write_bytes(content)
                git(worktree, "add", "--", *changed)
                if git(worktree, "diff", "--cached", "--quiet", check=False).returncode == 0:
                    print("Memory is already saved remotely.")
                    return False
                git(worktree, "-c", "user.name=github-actions[bot]",
                    "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                    "commit", "-m", f"chore: retain {track} pipeline memory")
                revision = git(worktree, "rev-parse", "HEAD").stdout.decode().strip()
                pushed = git(root, "push", "origin", f"{revision}:refs/heads/{branch}", check=False)
                if pushed.returncode == 0:
                    print(f"Saved {len(changed)} {track} memory files.")
                    return True
                # Retry a non-fast-forward race from a fresh remote base.
                if attempt == attempts - 1:
                    raise RuntimeError("Memory push failed; recover from the run's memory artifact.\n"
                                       + pushed.stderr.decode())
            finally:
                git(root, "worktree", "remove", "--force", str(worktree))
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track", choices=MEMORY_FILES, required=True)
    parser.add_argument("--branch", required=True)
    args = parser.parse_args()
    persist(Path(__file__).resolve().parents[1], args.track, args.branch)


if __name__ == "__main__":
    main()
