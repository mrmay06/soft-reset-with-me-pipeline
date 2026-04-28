import os

from utils.helpers import load_json, save_json, now_iso

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


def _sanitize_tags(tags: list) -> list:
    """
    YouTube tag rules:
    - Each tag: max 30 chars (strip to fit)
    - No special chars: < > & " '
    - Combined total: max 450 chars (conservative, API limit is 500)
    """
    import re
    clean = []
    total = 0
    for tag in tags:
        t = re.sub(r'[<>&"\']', '', str(tag)).strip()
        t = t[:30]  # hard cap per tag
        if not t:
            continue
        if total + len(t) > 400:
            break
        clean.append(t)
        total += len(t)
    return clean


def run_upload(video_id: str, run_dir: str, config: dict) -> dict:
    print(f"[uploader] Uploading video {video_id} to YouTube")

    metadata = load_json(os.path.join(run_dir, "07_metadata.json"))
    video_path = os.path.join(run_dir, "06_final_video.mp4")
    thumbnail_path = os.path.join(run_dir, "05_thumbnail.png")

    youtube = _get_youtube_client()

    tags = _sanitize_tags(metadata["tags"])
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

    result = {
        "video_id": video_id,
        "youtube_video_id": youtube_video_id,
        "youtube_url": youtube_url,
        "title": metadata["title"],
        "privacy_status": metadata["privacy_status"],
        "thumbnail_set": thumbnail_set,
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
