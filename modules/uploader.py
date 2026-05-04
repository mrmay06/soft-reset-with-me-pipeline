from __future__ import annotations
import os

from utils.helpers import load_json, save_json, now_iso
from utils.youtube_tags import sanitize_youtube_tags

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
except ImportError:
    Credentials = None


def _get_youtube_client():
    if Credentials is None:
        raise RuntimeError("google-api-python-client not installed")
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YOUTUBE_REFRESH_TOKEN"],
        client_id=os.environ["YOUTUBE_CLIENT_ID"],
        client_secret=os.environ["YOUTUBE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/youtube"],
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)


def _post_engagement_comment(youtube, youtube_video_id: str, engagement_question: str) -> str | None:
    """Post the engagement question as a comment immediately after upload. Returns comment_id or None."""
    if not engagement_question or not engagement_question.strip():
        return None
    try:
        body = {
            "snippet": {
                "videoId": youtube_video_id,
                "topLevelComment": {
                    "snippet": {
                        "textOriginal": engagement_question.strip()
                    }
                }
            }
        }
        result = youtube.commentThreads().insert(part="snippet", body=body).execute()
        comment_id = result["snippet"]["topLevelComment"]["id"]
        print(f"[uploader] Engagement comment posted ✅  (id: {comment_id})")
        return comment_id
    except Exception as e:
        print(f"[uploader] Comment post failed (comments may be disabled or API error): {e}")
        return None


def run_upload(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[uploader] Uploading video {video_id} to YouTube")

    metadata = load_json(os.path.join(run_dir, "07_metadata.json"))
    script   = load_json(os.path.join(run_dir, "02_script.json"))
    video_path = os.path.join(run_dir, "06_final_video.mp4")
    thumbnail_path = os.path.join(run_dir, "05_thumbnail.png")

    youtube = _get_youtube_client()

    tags = sanitize_youtube_tags(
        metadata["tags"],
        config.get("youtube_tags_total_chars", 300),
        config.get("youtube_tags_max_count", 15),
    )
    print(f"[uploader] Sending {len(tags)} tags, {sum(len(t) for t in tags)} total chars")

    body = {
        "snippet": {
            "title": metadata["title"],
            "description": metadata["description"],
            "tags": tags,
            "categoryId": metadata["category_id"],
            "defaultAudioLanguage": "en",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": metadata["privacy_status"],
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True, chunksize=10 * 1024 * 1024)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[uploader] Upload progress: {int(status.progress() * 100)}%")

    youtube_video_id = response["id"]
    youtube_url = f"https://youtube.com/shorts/{youtube_video_id}"

    thumbnail_set = False
    try:
        youtube.thumbnails().set(
            videoId=youtube_video_id,
            media_body=MediaFileUpload(thumbnail_path, mimetype="image/png")
        ).execute()
        thumbnail_set = True
    except Exception as e:
        print(f"[uploader] Thumbnail set failed (channel may not be verified): {e}")

    # Auto-post engagement question as first comment to seed algorithm conversation
    engagement_question = script.get("engagement_question", "")
    comment_id = _post_engagement_comment(youtube, youtube_video_id, engagement_question)

    result = {
        "video_id": video_id,
        "youtube_video_id": youtube_video_id,
        "youtube_url": youtube_url,
        "title": metadata["title"],
        "privacy_status": metadata["privacy_status"],
        "thumbnail_set": thumbnail_set,
        "engagement_comment_id": comment_id,
        "uploaded_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "08_upload_meta.json"))
    print(f"[uploader] Done. URL: {youtube_url}")
    return result


def run_upload_mock(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[uploader][MOCK] Skipping upload (mock mode)")
    result = {
        "video_id": video_id,
        "youtube_video_id": "MOCK_NOT_UPLOADED",
        "youtube_url": "https://youtube.com/shorts/MOCK_NOT_UPLOADED",
        "title": "MOCK",
        "privacy_status": config["privacy_status"],
        "thumbnail_set": False,
        "uploaded_at": now_iso(),
    }
    save_json(result, os.path.join(run_dir, "08_upload_meta.json"))
    return result
