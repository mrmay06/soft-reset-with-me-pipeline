from __future__ import annotations

import os
import time

from utils.helpers import load_json, save_json, now_iso
from utils.notify import send_auth_expiry_alert, send_longform_upload_confirmation
from utils.youtube_tags import sanitize_youtube_tags

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from google.auth.exceptions import RefreshError
except ImportError:
    Credentials = None
    RefreshError = Exception


def _get_youtube_client():
    if Credentials is None:
        raise RuntimeError("google-api-python-client not installed")
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
        send_auth_expiry_alert("Longform uploader")
        raise RuntimeError(
            "YouTube refresh token expired or revoked. Run tools/get_youtube_token.py "
            "and update YOUTUBE_REFRESH_TOKEN. Channel is paused until fixed."
        ) from exc
    return build("youtube", "v3", credentials=creds)


def _set_thumbnail_with_retry(youtube, youtube_video_id: str, thumbnail_path: str, max_attempts: int = 3) -> bool:
    for attempt in range(1, max_attempts + 1):
        try:
            youtube.thumbnails().set(
                videoId=youtube_video_id,
                media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
            ).execute()
            print(f"[longform_uploader] Thumbnail set ✅")
            return True
        except Exception as exc:
            if attempt < max_attempts:
                wait = attempt * 10
                print(f"[longform_uploader] Thumbnail set failed (attempt {attempt}/{max_attempts}): {exc} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"[longform_uploader] Thumbnail set failed after {max_attempts} attempts — channel may not be verified: {exc}")
    return False


def _post_engagement_comment(youtube, youtube_video_id: str, engagement_question: str) -> str | None:
    if not engagement_question or not engagement_question.strip():
        return None
    try:
        body = {
            "snippet": {
                "videoId": youtube_video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": engagement_question.strip()}
                },
            }
        }
        result = youtube.commentThreads().insert(part="snippet", body=body).execute()
        comment_id = result["snippet"]["topLevelComment"]["id"]
        print(f"[longform_uploader] Engagement comment posted (id: {comment_id})")
        return comment_id
    except Exception as exc:
        print(f"[longform_uploader] Comment post failed: {exc}")
        return None


def run_longform_upload(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_uploader] Uploading {video_id} to YouTube")

    metadata = load_json(os.path.join(run_dir, "03_longform_metadata.json"))
    script = load_json(os.path.join(run_dir, "02_longform_script.json"))
    video_path = os.path.join(run_dir, "06_longform_video.mp4")
    thumbnail_path = os.path.join(run_dir, "07_longform_thumbnail.png")

    youtube = _get_youtube_client()

    tags = sanitize_youtube_tags(
        metadata.get("tags", []),
        config.get("youtube_tags_total_chars", 450),
        config.get("youtube_tags_max_count", 15),
    )
    print(f"[longform_uploader] {len(tags)} tags, {sum(len(t) for t in tags)} chars")

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": tags,
            "categoryId": str(metadata.get("category_id", config.get("youtube_category_id", "27"))),
            "defaultAudioLanguage": "en",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": metadata.get("privacy_status", config.get("privacy_status", "private")),
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=10 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[longform_uploader] Upload progress: {int(status.progress() * 100)}%")

    youtube_video_id = response["id"]
    youtube_url = f"https://www.youtube.com/watch?v={youtube_video_id}"

    thumbnail_set = False
    if os.path.exists(thumbnail_path):
        thumbnail_set = _set_thumbnail_with_retry(youtube, youtube_video_id, thumbnail_path)
    else:
        print(f"[longform_uploader] Thumbnail not found at {thumbnail_path} — skipping")

    engagement_question = script.get("engagement_question", "")
    comment_id = _post_engagement_comment(youtube, youtube_video_id, engagement_question)

    thumbnail_meta = {}
    thumbnail_meta_path = os.path.join(run_dir, "07_longform_thumbnail_meta.json")
    if os.path.exists(thumbnail_meta_path):
        thumbnail_meta = load_json(thumbnail_meta_path)

    # Update topic memory entry with live YouTube IDs
    memory_file = config.get("topic_memory_file", "topic_memory_soft_reset_long.json")
    if os.path.exists(memory_file):
        memory = load_json(memory_file)
        if isinstance(memory, list):
            for entry in memory:
                if entry.get("video_id") == video_id:
                    entry["youtube_video_id"] = youtube_video_id
                    entry["youtube_url"] = youtube_url
                    entry["status"] = "uploaded"
                    break
            save_json(memory, memory_file)

    result = {
        "video_id": video_id,
        "youtube_video_id": youtube_video_id,
        "youtube_url": youtube_url,
        "title": metadata["title"],
        "primary_variant_id": metadata.get("primary_variant_id", ""),
        "privacy_status": metadata.get("privacy_status", config.get("privacy_status", "private")),
        "thumbnail_set": thumbnail_set,
        "engagement_comment_id": comment_id,
        "uploaded_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "09_longform_upload_meta.json"))
    send_longform_upload_confirmation(
        video_id=video_id,
        title=metadata["title"],
        youtube_url=youtube_url,
        metadata=metadata,
        thumbnail_meta=thumbnail_meta,
        run_dir=run_dir,
    )
    print(f"[longform_uploader] Done. URL: {youtube_url}")
    return result


def run_longform_upload_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[longform_uploader][MOCK] Skipping upload (mock mode)")
    result = {
        "video_id": video_id,
        "youtube_video_id": "MOCK_NOT_UPLOADED",
        "youtube_url": "https://www.youtube.com/watch?v=MOCK_NOT_UPLOADED",
        "title": "MOCK",
        "primary_variant_id": "B",
        "privacy_status": config.get("privacy_status", "private"),
        "thumbnail_set": False,
        "engagement_comment_id": None,
        "uploaded_at": now_iso(),
        "mock": True,
    }
    save_json(result, os.path.join(run_dir, "09_longform_upload_meta.json"))
    return result
