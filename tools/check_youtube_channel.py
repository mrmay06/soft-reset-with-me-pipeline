from __future__ import annotations

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
except ImportError as exc:
    raise SystemExit("Run: pip install google-api-python-client google-auth") from exc


def main() -> None:
    load_dotenv(override=True)
    required = ["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"]
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=[
            "https://www.googleapis.com/auth/youtube",
            "https://www.googleapis.com/auth/yt-analytics.readonly",
        ],
    )
    creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds)
    analytics = build("youtubeAnalytics", "v2", credentials=creds)

    response = youtube.channels().list(part="snippet,statistics", mine=True).execute()
    channels = response.get("items", [])
    if not channels:
        raise SystemExit("No YouTube channel found for this OAuth token.")

    print("Authenticated YouTube channel(s):")
    for channel in channels:
        snippet = channel.get("snippet", {})
        stats = channel.get("statistics", {})
        print(f"- {snippet.get('title', '(untitled)')} | id={channel.get('id')} | videos={stats.get('videoCount', '0')}")

    end = datetime.utcnow().date() - timedelta(days=1)
    start = end - timedelta(days=7)
    analytics.reports().query(
        ids="channel==MINE",
        startDate=start.isoformat(),
        endDate=end.isoformat(),
        metrics="views",
        maxResults=1,
    ).execute()
    print("YouTube Analytics API: OK")


if __name__ == "__main__":
    main()
