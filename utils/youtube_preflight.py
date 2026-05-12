from __future__ import annotations

import os

from utils.notify import send_auth_expiry_alert

try:
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
except ImportError:
    Credentials = None
    RefreshError = Exception


REQUIRED_YOUTUBE_ENV = (
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REFRESH_TOKEN",
)


def check_youtube_refresh_token(service: str) -> None:
    """Fail fast if the YouTube refresh token cannot mint an access token."""
    if Credentials is None:
        raise RuntimeError("google-auth is not installed; cannot validate YouTube OAuth token.")

    missing = [name for name in REQUIRED_YOUTUBE_ENV if not os.environ.get(name)]
    if missing:
        raise RuntimeError(
            "Missing YouTube OAuth environment variables: "
            + ", ".join(missing)
            + ". Update .env / GitHub Secrets before running the pipeline."
        )

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube.force-ssl"],
    )

    try:
        creds.refresh(Request())
    except RefreshError as exc:
        send_auth_expiry_alert(service)
        raise RuntimeError(
            "YouTube refresh token expired or revoked. Run tools/get_youtube_token.py "
            "and update YOUTUBE_REFRESH_TOKEN. Channel is paused before generation."
        ) from exc

    print(f"[preflight] YouTube OAuth refresh token OK for {service}")
