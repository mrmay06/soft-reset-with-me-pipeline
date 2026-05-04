"""
One-time script to get your YouTube OAuth refresh token.

Steps:
  1. Run:  python tools/get_youtube_token.py
  2. It opens your browser for Google login — sign in with your YouTube channel account
  3. Copy the refresh_token it prints
  4. Paste it into .env → YOUTUBE_REFRESH_TOKEN=<token>

Requires: pip install google-auth-oauthlib
"""

import os
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID     = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
REDIRECT_URI  = "http://localhost:8080/"
SCOPES        = ["https://www.googleapis.com/auth/youtube.upload",
                 "https://www.googleapis.com/auth/youtube",
                 "https://www.googleapis.com/auth/youtube.force-ssl",
                 "https://www.googleapis.com/auth/yt-analytics.readonly"]  # analytics feedback loop

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    raise SystemExit("Run: pip install google-auth-oauthlib")

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uris": [REDIRECT_URI],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}

flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)
creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")

print("\n" + "=" * 60)
print("SUCCESS — add this to your .env file:")
print("=" * 60)
print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
print("=" * 60)
