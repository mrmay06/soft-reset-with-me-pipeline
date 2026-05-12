#!/usr/bin/env python3
"""
One-command YouTube OAuth repair.

Run from the Relation repo:
  python3 tools/start_youtube_reauth.py

What it does:
  1. Opens Google consent in your browser.
  2. Captures the new refresh token on localhost:8080.
  3. Updates YOUTUBE_REFRESH_TOKEN in this pipeline's local .env file.
  4. Updates YOUTUBE_REFRESH_TOKEN in this pipeline's GitHub repo secret via gh.
  5. Verifies the new token can refresh.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv


RELATION_REPO = Path("/Users/mayurdusane/Documents/Relation-shots")
LOCAL_ENV_FILES = (
    RELATION_REPO / ".env",
)
GITHUB_REPOS = (
    "mrmay06/soft-reset-with-me-pipeline",
)
REDIRECT_URI = "http://localhost:8080/"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError as exc:
    raise SystemExit("Run: pip install google-auth-oauthlib google-auth") from exc


def _load_environment() -> None:
    for env_path in LOCAL_ENV_FILES:
        if env_path.exists():
            load_dotenv(env_path, override=False)
    load_dotenv(override=False)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing {name}. Add it to .env before running this repair tool.")
    return value


def _write_env_value(path: Path, key: str, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.exists() else ""
    line = f"{key}={value}"
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(existing):
        updated = pattern.sub(line, existing)
    else:
        updated = existing.rstrip("\n")
        updated = f"{updated}\n{line}\n" if updated else f"{line}\n"
    path.write_text(updated)
    print(f"[reauth] Updated local secret: {path}")


def _set_github_secret(repo: str, token: str) -> None:
    if shutil.which("gh") is None:
        print("[reauth] GitHub CLI not found; skipping GitHub Secrets update.")
        return

    auth_check = subprocess.run(
        ["gh", "auth", "status"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if auth_check.returncode != 0:
        print("[reauth] gh is not authenticated; skipping GitHub Secrets update.")
        print("         Run: gh auth login")
        return

    result = subprocess.run(
        ["gh", "secret", "set", "YOUTUBE_REFRESH_TOKEN", "--repo", repo],
        input=token,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to update GitHub secret for {repo}: {result.stderr.strip()}")
    print(f"[reauth] Updated GitHub secret: {repo}/YOUTUBE_REFRESH_TOKEN")


def _verify_refresh_token(refresh_token: str, client_id: str, client_secret: str) -> None:
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    print("[reauth] Verified new refresh token.")


def _run_oauth_flow(flow: InstalledAppFlow):
    try:
        return flow.run_local_server(port=8080, prompt="consent", access_type="offline")
    except OSError as exc:
        if getattr(exc, "errno", None) != 48:
            raise
        raise RuntimeError(
            "Could not start the local Google OAuth callback server because "
            "localhost:8080 is already in use. Run:\n"
            "  lsof -nP -iTCP:8080 -sTCP:LISTEN\n"
            "Then stop the stale process and rerun this tool."
        ) from exc


def main() -> int:
    _load_environment()
    client_id = _require_env("YOUTUBE_CLIENT_ID")
    client_secret = _require_env("YOUTUBE_CLIENT_SECRET")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": [REDIRECT_URI],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    print("[reauth] Opening Google consent in your browser.")
    print("[reauth] Choose the Soft Reset With Me YouTube channel Google account, then click Allow.")
    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
    creds = _run_oauth_flow(flow)

    if not creds.refresh_token:
        raise RuntimeError(
            "Google did not return a refresh token. Re-run this tool and make sure "
            "you approve the consent screen."
        )

    _verify_refresh_token(creds.refresh_token, client_id, client_secret)

    for env_path in LOCAL_ENV_FILES:
        _write_env_value(env_path, "YOUTUBE_REFRESH_TOKEN", creds.refresh_token)

    for repo in GITHUB_REPOS:
        _set_github_secret(repo, creds.refresh_token)

    print("\n[reauth] Done. You can rerun the failed pipeline now.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
